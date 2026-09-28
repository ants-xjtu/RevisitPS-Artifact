"""Reuse completed readiness reports without caching fabric/NIC configuration."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time

import yaml

from framework.environment import ROOT, check_agent, check_summary, source_digest
from framework.progress import progress


CHECK_SOURCES = ('framework/environment.py', 'framework/remote.py',
                 'framework/nix_environment.py', 'framework/environment_cache.py')


def readiness_identity(deployment, hosts, switches):
    """Only inputs read by Environment.check, not per-experiment NIC/P4 settings."""
    rdma = deployment['rdma']
    tofino = deployment['tofino']
    return {
        'deployment': {
            **{key: deployment.get(key) for key in
               ('ssh', 'packages', 'remote_root', 'minimum_free_kib', 'perftest')},
            'rdma': {key: rdma.get(key) for key in ('user', 'stack', 'packages')},
            'tofino': {key: tofino.get(key) for key in
                       ('user', 'sde_command', 'install_command', 'nix_daemon_start_command',
                        'device_path', 'module_path')},
        },
        'hosts': {ip: {'user': host.get('user', rdma['user']),
                       **{key: host.get(key) for key in
                          ('hostname', 'eth', 'bus_info', 'mlx_device_name')}}
                  for ip, host in hosts.items()},
        'switches': {name: {'user': switch.get('user', tofino['user']),
                            'management': switch.get('management', name)}
                     for name, switch in switches.items()},
    }


def identity_covers(checked, requested):
    """A union-of-devices readiness check also covers any unchanged subset."""
    return (checked.get('deployment') == requested.get('deployment') and
            all(all(checked.get(kind, {}).get(name) == item for name, item in requested[kind].items())
                for kind in ('hosts', 'switches')))


def implementation_identity(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in CHECK_SOURCES}


def complete_report(report, identity, perftest_digest):
    checks = report.get('checks', [])
    if (not checks or report.get('current') or
            any(row.get('status') != 'passed' or row.get('passed') is not True for row in checks)):
        return False
    rows = {(row['target'], row['item']): row for row in checks}
    required = {('local', 'ssh-agent')}
    rdma_targets = {f"{host['user']}@{host['hostname']}" for host in identity['hosts'].values()}
    switch_targets = {f"{switch['user']}@{switch['management']}" for switch in identity['switches'].values()}
    for target in rdma_targets | switch_targets:
        required.update((target, item) for item in ('management', 'permissions', 'packages'))
    for target in switch_targets:
        required.update((target, item) for item in ('nix', 'sde', 'bf_kdrv'))
    for target in rdma_targets:
        required.update((target, item) for item in ('storage', 'rdma-stack', 'tool:ibv_devinfo',
                                                   'tool:mlxreg', 'tool:mlnx_qos', 'verbs',
                                                   'memlock', 'perftest'))
        if (identity['deployment']['rdma']['stack'] == 'inbox' and
                rows.get((target, 'rdma-stack'), {}).get('detail') == 'inbox'):
            required.add((target, 'rdma-packages'))
        binary = report.get('perftest', {}).get(target, {})
        if (not binary.get('path') or binary.get('source_sha256') != perftest_digest or
                binary.get('build') != identity['deployment']['perftest']['build_command'] or
                (os.environ.get('PERFTEST_COMMIT') and binary.get('commit') != os.environ['PERFTEST_COMMIT'])):
            return False
    for ip, host in identity['hosts'].items():
        target = f"{host['user']}@{host['hostname']}/{ip}"
        required.update((target, item) for item in ('mapping', 'port-inventory'))
    return required.issubset(rows)


def find_report(results_dir, identity, implementation, perftest_digest):
    """The newest matching check wins, including failures (no stale fallback).

    Pre-cache run reports are supported using their original input/source
    snapshots. Historical reports without these snapshots are not reused.
    """
    candidates = []
    paths = set(results_dir.glob('*/environment.json'))
    paths.update(results_dir.glob('*/tasks/*/attempt-*/environment.json'))
    paths.update(results_dir.glob('*/checks/*/environment.json'))
    paths.update(results_dir.glob('*/checks/common/*/environment.json'))
    paths.update(results_dir.glob('*/preparation/*/environment.json'))
    for path in paths:
        try:
            report = json.loads(path.read_text())
            metadata = report.get('readiness_cache')
            if metadata:
                previous = metadata.get('identity', {})
                if (metadata.get('version') != 1 or
                        metadata.get('implementation') != implementation):
                    continue
                covers = identity_covers(previous, identity)
                # A newer failed subset invalidates an older union report too.
                overlaps = (previous.get('deployment') == identity['deployment'] and
                            any(name in previous.get(kind, {}) for kind in ('hosts', 'switches')
                                for name in identity[kind]))
                failed = (metadata.get('complete') is not True or
                          not complete_report(report, previous, perftest_digest))
                if not covers and not (overlaps and failed):
                    continue
                checked_at = metadata['checked_at']
            else:
                # A legacy attempt keeps the exact effective deployment and
                # endpoint configuration alongside its environment report.
                config_dir = path.parent / 'configs'
                if not (config_dir / 'deployment.yaml').is_file():
                    continue
                def read(name):
                    return yaml.safe_load((config_dir / name).read_text())
                previous = readiness_identity(read('deployment.yaml'), read('hosts.yaml')['hosts'],
                                              read('switches.yaml')['switches'])
                run_dir = results_dir / path.relative_to(results_dir).parts[0]
                previous_code = implementation_identity(run_dir / 'configs/implementation')
                if previous != identity or previous_code != implementation:
                    continue
                checked_at = path.stat().st_mtime
            candidates.append((checked_at, path, report))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        return None
    checked_at, path, report = max(candidates, key=lambda row: (row[0], str(row[1])))
    if report.get('readiness_cache', {}).get('complete') is False:
        return None
    if not complete_report(report, identity, perftest_digest):
        return None
    return path, checked_at, report


def prepare_environment(environment, hosts, switches, results_dir, refresh=False, prepare=True):
    identity = readiness_identity(environment.config, hosts, switches)
    implementation = implementation_identity(ROOT)
    perftest_digest = source_digest(ROOT / 'experiments/dcn_workload/sources/perftest')
    cached = None if refresh else find_report(Path(results_dir), identity, implementation, perftest_digest)
    if cached:
        path, checked_at, previous = cached
        # A report does not authenticate the current SSH agent.
        fingerprints = check_agent(environment.config['ssh']['expected_fingerprints'])
        environment.report = copy.deepcopy(previous)
        environment.report['fingerprints'] = fingerprints
        for row in environment.report['checks']:
            if row['target'] == 'local' and row['item'] == 'ssh-agent':
                row['detail'] = fingerprints
        # Do not carry another algorithm's mlxreg values into this report.
        discovered = copy.deepcopy(hosts)
        for ip, host in discovered.items():
            old = previous.get('discovered_hosts', {}).get(ip, {})
            for field in ('mlx_device_name', 'bus_info'):
                if field in old:
                    host[field] = old[field]
        environment.report['discovered_hosts'] = discovered
        environment.report['readiness_cache'] = dict(
            version=1, identity=identity, implementation=implementation,
            checked_at=checked_at, complete=True, reused_from=str(path), reused_at=time.time())
        environment.save()
        progress(f"Reusing {check_summary(previous['checks'])['passed']} passed environment checks: {path}")
        return environment.report
    environment.report['readiness_cache'] = dict(
        version=1, identity=identity, implementation=implementation,
        checked_at=time.time(), complete=False)
    environment.save()
    report = environment.check(hosts, switches, prepare=prepare)
    report['readiness_cache']['complete'] = True
    environment.save()
    return report
