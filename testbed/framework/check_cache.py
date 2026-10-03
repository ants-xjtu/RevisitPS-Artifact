"""Shared readiness batches and per-algorithm DCN traffic validation."""
import copy
import json
import os
import re

from framework.results import atomic_json, canonical_hash, digest
from framework.environment_cache import readiness_identity


def readiness_batches(selected, deployment):
    from framework.runner import validate, experiment_deployment
    batches = {}
    for experiment in selected:
        effective = experiment_deployment(deployment, experiment)
        _, _, hosts, switches, _ = validate(experiment)
        key = canonical_hash(readiness_identity(effective, {}, {})['deployment'])
        batch = batches.setdefault(key, dict(deployment=effective, hosts={}, switches={}, experiments=[]))
        for kind, entries in (('hosts', hosts), ('switches', switches)):
            for name, entry in entries.items():
                # Network-mode registers are not part of shared environment checks.
                if name in batch[kind]:
                    old = readiness_identity(effective, {name: batch[kind][name]} if kind == 'hosts' else {},
                                             {name: batch[kind][name]} if kind == 'switches' else {})[kind]
                    new = readiness_identity(effective, {name: entry} if kind == 'hosts' else {},
                                             {name: entry} if kind == 'switches' else {})[kind]
                    if old != new:
                        raise ValueError('Conflicting shared device inventory: ' + name)
                batch[kind][name] = copy.deepcopy(entry)
        batch['experiments'].append(experiment)
    return batches


def traffic_identity(experiment, deployment):
    from framework.runner import ROOT, validate, yaml_read, perftest_commit
    config, refs, hosts, switches, links = validate(experiment)
    commands = copy.deepcopy(config['applications']['remote_rdma'])
    # QP timeout is intentionally mode-specific; the user selected one
    # representative traffic test per algorithm, not one per network mode.
    commands = {name: {k: re.sub(r'--qp-timeout=\d+', '--qp-timeout=MODE', v)
                       if isinstance(v, str) else v for k, v in commands[name]['cmd'].items()}
                for name in ('check', 'test')}
    sources = {str(p.relative_to(ROOT)): digest(p)
               for folder in ('framework', 'switches', 'experiments/dcn_workload/scripts')
               for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in ('.py', '.p4', '.sh')}
    return dict(policy='one-representative-mode-per-algorithm-v1', algorithm=experiment['algorithm'],
                readiness=readiness_identity(deployment, hosts, switches),
                topology=yaml_read(refs['topo']), links=links,
                programs={name: sw['program'] for name, sw in switches.items()},
                measurement=deployment['measurement'], commands=commands,
                dcqcn={key: deployment['rdma'].get(key) for key in
                       ('dcqcn', 'dcqcn_overrides', 'dcqcn_parameters')},
                sources=sources, perftest=perftest_commit(),
                dependencies=digest(ROOT / 'docker/requirements.lock.txt'),
                image=os.environ.get('ARTIFACT_IMAGE_ID', 'native'))


def cached_traffic(run_dir, identity):
    path = run_dir / 'checks/traffic' / (canonical_hash(identity) + '.json')
    try:
        record = json.loads(path.read_text())
        if record['identity'] != identity or record['status'] != 'passed' or not record['files']:
            return path, None
        if not all((run_dir / name).is_file() and digest(run_dir / name) == checksum
                   for name, checksum in record['files'].items()):
            return path, None
        return path, record
    except (OSError, ValueError, KeyError, TypeError):
        return path, None


def traffic_once(experiment, deployment, run_dir, attempt, environment, action, refreshed=None,
                 *, identity=None, evidence_dir=None):
    if identity is None:
        identity = traffic_identity(experiment, deployment)
    path, cached = cached_traffic(run_dir, identity)
    key = canonical_hash(identity)
    # An explicit refresh invalidates each algorithm once, not once per mode.
    if refreshed is not None and key not in refreshed:
        cached = None
        refreshed.add(key)
    if cached:
        detail = dict(source_experiment=cached['experiment'], tested_mode=cached['mode'],
                      source_attempt=cached['attempt'], cache=str(path),
                      scope='algorithm-level traffic only; current-mode configuration read back separately')
        environment.record(experiment['id'], 'traffic-reuse', lambda: detail)
        from framework.progress import progress
        progress(f"Reusing {experiment['algorithm']} traffic check from {cached['experiment']}")
        return dict(detail, reused=True)
    record = dict(identity=identity, experiment=experiment['id'], mode=experiment['group'],
                  attempt=str(attempt.relative_to(run_dir)), status='running', files={})
    atomic_json(path, record)
    try:
        action()
        record['files'] = {str(p.relative_to(run_dir)): digest(p)
                           for p in (evidence_dir if evidence_dir is not None else attempt / 'checks').rglob('*')
                           if p.is_file()}
        if not record['files']:
            raise ValueError('Traffic validation produced no check evidence')
        record['status'] = 'passed'
    except BaseException as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        atomic_json(path, record)

    return dict(source_experiment=experiment['id'], tested_mode=experiment['group'],
                source_attempt=record['attempt'], cache=str(path), reused=False)
