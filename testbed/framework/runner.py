#!/usr/bin/env python3
"""Shared experiment orchestration, persistent state and exclusive device ownership."""
import argparse
import contextlib
import copy
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT.parent / 'plot'):
    sys.path.insert(0, str(path))
import yaml
from framework.environment import Environment, CheckFailed, check_summary
from framework.remote import RemoteRDMAHelper, logged_run, ssh_spacing, SSHConnectionError
from framework.progress import progress, stage
from framework.results import atomic_json, digest, canonical_hash, intact, manifest, persist
from framework.conf_parser.yaml_parser import TestConfParser





def yaml_read(path):
    with open(path) as stream:
        return yaml.safe_load(stream)


def local_path(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def expand_experiments(registry, selection):
    """Select a paper experiment and expand its algorithm variants."""
    selected = []
    for entry in registry:
        if selection not in ("all", entry["id"]):
            continue
        for variant in entry.get("variants", [None]):
            spec = {key: copy.deepcopy(value) for key, value in entry.items() if key != "variants"}
            if variant is not None:
                spec.update(copy.deepcopy(variant))
                spec["id"] = entry["id"] + "-" + variant["id"]
            selected.append(spec)
    return selected


def experiment_deployment(deployment, experiment):
    result = copy.deepcopy(deployment)
    profiles = result.pop('experiment_overrides', {})
    merge(result, profiles.get(experiment['group'], {}))
    merge(result, profiles.get(experiment['id'], {}))
    if experiment.get('nic_registers'):
        result['rdma']['psn_window_packets'] = 128
    merge(result, experiment.get('deployment_overrides', {}))
    measurement = result['measurement']
    if measurement['threshold_gbps'] < 90:
        raise ValueError('Experiment overrides cannot lower the 90 Gbps acceptance threshold')
    return result


def validate(experiment):
    config = yaml_read(local_path(experiment['config']))
    merge(config, experiment.get('config_overrides', {}))
    refs = {key: local_path(value) for key, value in config['config'].items()}
    for path in refs.values():
        if not path.is_file():
            raise ValueError(f'Missing configuration reference: {path}')
    hosts = yaml_read(refs['hosts'])['hosts']
    for host in hosts.values():
        merge(host.setdefault('mlxreg', {}), experiment.get('nic_registers', {}))
    connections = yaml_read(refs['connections'])['connections']
    if not connections:
        raise ValueError('Empty connection list')
    for link in connections:
        for end in ('sender', 'receiver'):
            if link[end] not in hosts:
                raise ValueError(f'Unknown endpoint: {link[end]}')
    if len({(c['sender'], c['receiver']) for c in connections}) != len(connections):
        raise ValueError('Duplicate connections would overwrite logs')
    switches = yaml_read(refs['switches'])['switches']
    from framework.conf_parser.yaml_parser import SwitchConfParser
    switch_parser = SwitchConfParser(str(refs['switches']))
    switch_parser.load_conf_file()
    for hostname in switches:
        switch_parser.parse_buffer_config(hostname)
        switch_parser.parse_dcqcn_config(hostname)
        switch_parser.parse_multicast_config(hostname)
        if not switch_parser.parse_ports(hostname):
            raise ValueError('Invalid/empty switch port configuration')
    topo = yaml_read(refs['topo'])
    for node in topo['switch_nodes'].values():
        if node['hostname'] not in switches:
            raise ValueError('Topology references an unknown switch')
    endpoints = set(hosts) | set(topo['switch_nodes'])
    if any(link[end] not in endpoints for link in topo['links'] for end in ('from', 'to')):
        raise ValueError('Topology references an unknown endpoint')
    for switch in switches.values():
        for field in ('path', 'cp_script_path'):
            path = local_path(switch['program'][field])
            if not path.is_file():
                raise ValueError(f'Missing switch source: {path}')
    if experiment['traffic'] == 'trace':
        refs['cdf'] = local_path(config['applications']['gen_trace']['cdf'])
        if not refs['cdf'].is_file():
            raise ValueError('CDF missing')
    for section in ('check', 'test'):
        cmd = config['applications']['remote_rdma'][section]['cmd']
        if not 1024 <= cmd['base_port'] < 65535 - len(connections):
            raise ValueError('Invalid/conflicting test port range')
    if config['applications']['remote_rdma']['check']['cmd']['config']['qp'] != 1:
        raise ValueError('Link acceptance requires the configured 1 QP baseline')
    return config, refs, hosts, switches, connections


def input_hash(experiment, deployment, repeat):
    config, refs, *_ = validate(experiment)
    # Include implementation and P4 includes, not just YAML filenames.
    sources = {str(p.relative_to(ROOT)): digest(p) for folder in ('switches', 'framework', 'experiments/dcn_workload/scripts')
               for p in (ROOT / folder).rglob('*') if p.suffix in ('.py', '.sh', '.p4') if '__pycache__' not in p.parts and 'results' not in p.parts}
    sources.update({str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'switches/programs').rglob('*.p4')})
    return canonical_hash(dict(experiment=experiment, deployment=deployment, repeat=repeat,
                               config=config, references={k: digest(v) for k, v in refs.items()}, sources=sources,
                               perftest=perftest_commit(), dependencies=digest(ROOT / 'docker/requirements.lock.txt'),
                               image=os.environ.get('ARTIFACT_IMAGE_ID', 'native')))


def perftest_commit():
    if os.environ.get('PERFTEST_COMMIT'):
        return os.environ['PERFTEST_COMMIT']
    source = ROOT / 'experiments/dcn_workload/sources/perftest'
    commit = logged_run(['git', '-C', str(source), 'rev-parse', 'HEAD']).stdout.strip()
    entry = logged_run(['git', '-C', str(ROOT.parent), 'ls-files', '-s', 'testbed/experiments/dcn_workload/sources/perftest']).stdout.split()
    if not entry or entry[0] != '160000' or entry[1] != commit or logged_run(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=all', '--ignored']).stdout.strip():
        raise ValueError('perftest source must match the clean parent gitlink')
    return commit


def snapshot(experiment, deployment, repeat, attempt):
    original, refs, hosts, switches, links = validate(experiment)
    folder = attempt / 'configs'
    folder.mkdir(parents=True, exist_ok=True)
    for key, path in refs.items():
        shutil.copy2(path, folder / (key + path.suffix))
    # Persist the effective algorithm-specific NIC settings, not the shared host defaults.
    (folder / 'hosts.yaml').write_text(yaml.safe_dump({'hosts': hosts}, sort_keys=False))
    (folder / 'source.yaml').write_text(yaml.safe_dump(original, sort_keys=False))
    (folder / 'deployment.yaml').write_text(yaml.safe_dump(deployment, sort_keys=False))
    runtime = copy.deepcopy(original)
    runtime['root_path'] = str(ROOT)
    runtime['config'] = {key: str(folder / (key + path.suffix)) for key, path in refs.items() if key != 'cdf'}
    runtime['log']['dir'] = str(attempt)
    runtime['artifact'] = {'measurement': deployment['measurement'], 'experiment': experiment,
                           'repeat': repeat}
    apps = runtime['applications']
    apps['remote_rdma']['user'] = deployment['rdma']['user']
    apps['remote_tofino']['user'] = deployment['tofino']['user']
    apps['analysis'] = {'input_folder': str(attempt / 'raw'), 'output_folder': str(attempt / 'parsed')}
    apps['plot'] = {'input_folder': str(attempt / 'raw'), 'output_folder': str(attempt / 'parsed')}
    if experiment['traffic'] == 'trace':
        apps['gen_trace']['cdf'] = str(folder / 'cdf.txt')
        apps['gen_trace']['seed'] = int(apps['gen_trace'].get('seed', 42)) + repeat - 1
    return runtime, hosts, switches, links


def save_runtime(runtime, attempt):
    path = attempt / 'configs/runtime.yaml'
    path.write_text(yaml.safe_dump(runtime, sort_keys=False))
    parser = TestConfParser(str(path))
    parser.load_conf_file()
    return parser


def prepare_runtime(runtime, report, attempt, run_id, task_id, deployment):
    apps = runtime['applications']
    remote_root = deployment['remote_root']
    # Resolve each device's own HOME, so differing accounts do not share guessed paths.
    hosts = yaml_read(runtime['config']['hosts'])['hosts']
    paths = {}
    for ip, host in hosts.items():
        target = f"{host.get('user', apps['remote_rdma']['user'])}@{host['hostname']}"
        if target not in report['perftest']:
            continue
        paths[ip] = report['perftest'][target]['path']
    # Templates receive binary_dir per endpoint (not one global remote HOME).
    runtime['artifact']['binary_paths'] = [{'ip': ip, 'path': path} for ip, path in paths.items()]
    remote_dir = f'{remote_root}/{run_id}/{task_id}/{attempt.name}'
    for section in ('check', 'test'):
        conf = apps['remote_rdma'][section]
        conf['local_log'] = str(attempt / ('raw' if section == 'test' else 'checks'))
        conf['remote_log'] = remote_dir + '/' + section
        for role in ('sender', 'receiver'):
            command = conf['cmd'][role].split('>')[0].strip()
            command = re.sub(r'(?:~/lib/perftest/)?(ib_write_(?:trace|bw))', r'{{binary_dir}}/\1', command)
            conf['cmd'][role] = 'stdbuf -oL -eL ' + command
        if section == 'check':
            # The fork uses -D as the interval in infinite mode.
            for role in ('sender', 'receiver'):
                conf['cmd'][role] += ' -D ' + str(runtime['artifact']['measurement']['interval_seconds']) + ' -f 0'
        conf.pop('kill_cmd', None)
    if runtime['artifact']['experiment']['traffic'] == 'trace':
        apps['gen_trace']['remote_path'] = remote_dir + '/trace'
        apps['remote_rdma']['test']['remote_trace_dir'] = remote_dir + '/trace'
    else:
        apps.pop('gen_trace', None)
        apps['remote_rdma']['test'].pop('remote_trace_dir', None)
    sde = deployment['tofino']['sde_command']
    apps['remote_tofino']['cmd'] = {
        'build': sde + " --command 'p4_build.sh {{p4program_path}}'",
        'deploy': sde + " --command 'run_switchd.sh -p {{p4program_name}}'",
        'config': sde + " --command 'export PYTHONPATH=$PYTHONPATH:.; python3 {{cp_script_path}} --hostname {{hostname}} --topo {{topo}} --switches {{switches}} --hosts {{hosts}} --bfrt-port {{port}}'"}
    return save_runtime(runtime, attempt)


def recover_processes(run_dir):
    groups = {}
    for journal in sorted(run_dir.glob('tasks/*/attempt-*/processes.jsonl')):
        for line in journal.read_text().splitlines():
            proc = json.loads(line)
            groups.setdefault(proc['target'], {})[proc['state']] = proc
    errors = []
    for target, processes in groups.items():
        user, hostname = target.split('@', 1)
        try:
            RemoteRDMAHelper(user, hostname).stop_many(processes.values())
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError('Process recovery failed: ' + '; '.join(errors))


def trace_inputs(*args, **kwargs):
    from experiments.dcn_workload.scripts.run import trace_inputs as implementation
    return implementation(*args, **kwargs)


def collect_and_validate(*args, **kwargs):
    from experiments.dcn_workload.scripts.run import collect_and_validate as implementation
    return implementation(*args, **kwargs)





@contextlib.contextmanager
def device_lock():
    folder = Path(os.environ.get('ARTIFACT_LOCK_DIR', ROOT / 'runtime/locks'))
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'testbed.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('The testbed is already held by another local artifact process')
        yield


def prepare_dcqcn(experiments, deployment):
    """Apply each distinct live DCQCN profile even on readiness cache hits."""
    from framework.rdma.config_nic import configure_dcqcn, dcqcn_values
    from framework.remote import generate_ip_helper_map
    prepared = set()
    for experiment in experiments:
        effective = experiment_deployment(deployment, experiment)
        _, _, hosts, _, _ = validate(experiment)
        rdma = effective['rdma']
        key = canonical_hash({'hosts': {ip: {k: host.get(k) for k in ('hostname', 'eth', 'user')}
                                        for ip, host in hosts.items()}, 'user': rdma['user'],
                              'dcqcn': {ip: dcqcn_values(rdma, ip) for ip in hosts}})
        if key in prepared:
            continue
        helpers = generate_ip_helper_map(hosts, hosts, rdma['user'])
        with stage('DCQCN preparation and readback'):
            configure_dcqcn(helpers, effective)
        prepared.add(key)


def check_experiment_traffic(experiment, deployment, run_dir, environment, built, *, cache_traffic=False, refreshed=None):
    """Active check: deploy the selected fabric, then validate both directions."""
    from framework.rdma.run_test import load_endpoints
    from framework.rdma.config_nic import configure
    from framework.rdma.check_link import check_links, verify_trace_support
    from switches.scripts.config_sw import run_switch_config
    directory = run_dir / 'checks' / experiment['id']
    attempt = directory / f'validation-{len(list(directory.glob("validation-*"))) + 1:03d}'
    attempt.mkdir(parents=True)
    updates = dict(ARTIFACT_COMMAND_LOG=str(attempt / 'commands.log'),
                   ARTIFACT_PROCESS_JOURNAL=str(attempt / 'processes.jsonl'),
                   ARTIFACT_SWITCH_LOG=str(run_dir / 'checks/switches'))
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        runtime, _, _, _ = snapshot(experiment, deployment, 1, attempt)
        parser = prepare_runtime(runtime, environment.report, attempt, run_dir.name,
                                 'check-' + experiment['id'], deployment)
        environment.record(experiment['id'], 'switch-deployment', lambda:
            run_switch_config(parser, do_build=True, do_run=True, do_config=True, built=built))
        host_parser, connections, helpers = load_endpoints(parser)
        environment.record(experiment['id'], 'nic-configuration', lambda:
            configure(host_parser, helpers, deployment, 'lossless' in experiment['group']))
        def traffic():
            environment.record(experiment['id'], 'bidirectional-throughput', lambda: check_links(parser))
            environment.record(experiment['id'], 'trace-format', lambda:
                verify_trace_support(parser, connections, helpers, attempt / 'checks/trace-smoke'))
        if cache_traffic:
            from framework.check_cache import traffic_once
            traffic_once(experiment, deployment, run_dir, attempt, environment, traffic, refreshed)
        else:
            traffic()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.copy2(environment.path, attempt / 'environment.json')


def run_task(*args, **kwargs):
    from experiments.dcn_workload.scripts.run import run_task as implementation
    return implementation(*args, **kwargs)


def parse_results(*args, **kwargs):
    from experiments.dcn_workload.scripts.parse import parse_results as implementation
    return implementation(*args, **kwargs)


def main(argv=None):
    from framework.environment_cache import prepare_environment
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', default='all', help='lossless, lossy, or all')
    parser.add_argument('--stage', choices=['check', 'prepare', 'run', 'status', 'parse', 'plot', 'all'], default='all')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--refresh-environment', action='store_true',
                        help='Run environment checks again instead of reusing the latest matching passed report')
    parser.add_argument('--deployment', type=Path, default=ROOT / 'deployment/deployment.yaml')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id) or args.repeat < 1:
        parser.error('run-id must contain only letters/digits/_/- and repeat must be positive')
    os.chdir(ROOT)
    run_dir = ROOT / 'results/dcn_workload' / args.run_id
    if args.stage in ('status', 'parse', 'plot') and not args.dry_run:
        status = json.loads((run_dir / 'status.json').read_text()) if (run_dir / 'status.json').exists() else {'tasks': {}}
        if args.stage == 'status':
            environment = json.loads((run_dir / 'environment.json').read_text()) if (run_dir / 'environment.json').exists() else None
            print(json.dumps(dict(status=status, environment=environment), indent=2))
        elif args.stage == 'parse':
            with stage('Result parsing'):
                parse_results(run_dir, status)
        else:
            with stage('Plotting'):
                from experiments.dcn_workload.scripts.plot import plot_results
                plot_results(run_dir)
            progress(f'Plotting complete: {run_dir / "figures"}')
        return
    deployment = yaml_read(args.deployment)
    measure = deployment['measurement']
    if measure['threshold_gbps'] < 90 or measure['duration_seconds'] <= 0 or measure['warmup_seconds'] < 0 or measure['interval_seconds'] < 1:
        raise ValueError('Require threshold >=90 Gbps and a valid fixed measurement window')
    registry = yaml_read(ROOT / 'experiments/dcn_workload/experiment.yaml')['experiments']
    selected = expand_experiments(registry, args.experiment)
    if not selected:
        parser.error('Unknown experiment id')
    for experiment in selected:
        validate(experiment)
    plan = [(e, repeat) for e in selected for repeat in range(1, args.repeat + 1)]
    if args.dry_run:
        print(json.dumps({'stage': args.stage, 'tasks': [dict(task_id=f'{e["id"]}-r{r:03d}', **e) for e, r in plan]}, indent=2))
        return
    os.environ['PERFTEST_COMMIT'] = perftest_commit()
    os.environ['ARTIFACT_RUN_ID'] = args.run_id
    with device_lock(), ssh_spacing():
        print('SSH pacing: at least 2 seconds between remote requests (all hosts).', flush=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        os.environ['ARTIFACT_COMMAND_LOG'] = str(run_dir / 'checks/commands.log')
        if args.stage in ('check', 'prepare'):
            from framework.check_cache import readiness_batches
            combined = {'checks': [], 'common': {}, 'experiments': {}}
            built = set()
            refreshed = set() if args.refresh_environment else None
            for key, batch in readiness_batches(selected, deployment).items():
                report_path = run_dir / 'checks/common' / key / 'environment.json'
                common = Environment(batch['deployment'], report_path)
                ready = True
                try:
                    prepare_environment(common, batch['hosts'], batch['switches'], run_dir.parent,
                                        refresh=args.refresh_environment, prepare=args.stage == 'prepare')
                except CheckFailed:
                    ready = False
                combined['common'][key] = copy.deepcopy(common.report)
                combined['checks'].extend(dict(item, experiment='common-' + key[:8])
                                          for item in common.report['checks'])
                if args.stage == 'prepare':
                    if not ready:
                        atomic_json(run_dir / 'environment.json', combined)
                        raise CheckFailed('Shared environment preparation failed')
                    prepare_dcqcn(batch['experiments'], deployment)
                    continue
                for experiment in batch['experiments']:
                    print(f"[check] Algorithm/mode configuration: {experiment['id']}", flush=True)
                    environment = Environment(experiment_deployment(deployment, experiment),
                                              run_dir / 'checks' / experiment['id'] / 'environment.json')
                    environment.report = copy.deepcopy(common.report)
                    environment.report.pop('readiness_cache', None)
                    environment.report['checks'] = []
                    environment.report['shared_readiness'] = str(report_path)
                    if not ready:
                        environment.report['checks'].append(dict(target=experiment['id'], item='active-validation',
                            passed=None, status='skipped', reason='Shared environment check failed'))
                        environment.save()
                    else:
                        try:
                            environment.record(experiment['id'], 'active-validation', lambda:
                                check_experiment_traffic(experiment, experiment_deployment(deployment, experiment),
                                                         run_dir, environment, built, cache_traffic=True,
                                                         refreshed=refreshed))
                        except SSHConnectionError:
                            raise
                        except Exception:
                            pass  # Failure is recorded; inspect other algorithms.
                    combined['experiments'][experiment['id']] = environment.report
                    combined['checks'].extend(dict(item, experiment=experiment['id'])
                                              for item in environment.report['checks'])
                combined['summary'] = check_summary(combined['checks'])
                atomic_json(run_dir / 'environment.json', combined)
            combined['summary'] = check_summary(combined['checks'])
            atomic_json(run_dir / 'environment.json', combined)
            if args.stage == 'check':
                summary = combined['summary']
                print(f"Check complete: {summary['passed']} passed, {summary['failed']} failed, "
                      f"{summary['skipped']} skipped. Report: {run_dir / 'environment.json'}")
                for item in combined['checks']:
                    if item['status'] != 'passed':
                        print(f"[{item['status']}] {item['experiment']} {item['target']} "
                              f"{item['item']}: {item.get('error', item.get('reason', ''))}")
                if summary['failed'] or summary['skipped']:
                    raise CheckFailed('Environment is not ready; see the completed check report')
            return
        status_path = run_dir / 'status.json'
        if status_path.exists() and not args.resume:
            raise ValueError('run-id already exists; use --resume or a new run-id')
        status = json.loads(status_path.read_text()) if status_path.exists() else {'run_id': args.run_id, 'tasks': {}}
        for experiment, repeat in plan:
            task_id = f'{experiment["id"]}-r{repeat:03d}'
            hashed = input_hash(experiment, experiment_deployment(deployment, experiment), repeat)
            if task_id in status['tasks'] and status['tasks'][task_id]['input_hash'] != hashed:
                raise ValueError(f'Resume configuration/source mismatch: {task_id}')
            status['tasks'].setdefault(task_id, dict(task_id=task_id, experiment=experiment['id'], repeat=repeat, status='pending', input_hash=hashed))
        persist(run_dir, status)
        if args.resume:
            # Identity validation is required before cleanup just as before deployment.
            from framework.environment import check_agent
            check_agent(deployment['ssh']['expected_fingerprints'])
            recover_processes(run_dir)
        atomic_json(run_dir / 'versions.json', {'project': os.environ.get('PROJECT_VERSION', 'local-working-tree'),
                    'image': os.environ.get('ARTIFACT_IMAGE_ID', 'native'), 'perftest': perftest_commit()})
        config_dir = run_dir / 'configs'
        if not config_dir.exists():
            for folder in ('deployment', 'switches', 'framework', 'experiments/dcn_workload/configs', 'experiments/dcn_workload/scripts'):
                shutil.copytree(ROOT / folder, config_dir / folder,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.local.yaml'))
        from framework.check_cache import readiness_batches
        for key, batch in readiness_batches(selected, deployment).items():
            with stage('Shared environment preparation'):
                prepare_environment(Environment(batch['deployment'],
                                    run_dir / 'checks/common' / key / 'environment.json'),
                                    batch['hosts'], batch['switches'], run_dir.parent,
                                    refresh=args.refresh_environment)
        from framework.rdma.run_test import TrafficExecutionError
        failed_tasks = []
        built = set()
        for task_number, (experiment, repeat) in enumerate(plan, 1):
            task = status['tasks'][f'{experiment["id"]}-r{repeat:03d}']
            progress(f'Task {task_number}/{len(plan)}: {task["task_id"]}')
            previous = copy.deepcopy(task)
            try:
                # Persist running before any remote work; preserve previous state for resume.
                task['status'] = 'running'
                persist(run_dir, status)
                task.update(previous)
                run_task(experiment, experiment_deployment(deployment, experiment), repeat, task, run_dir,
                         args.resume, built, status, refresh_environment=False)
            except BaseException as exc:
                task.update(status='failed', finished=time.time(), exit_code=1, error=str(exc))
                persist(run_dir, status)
                progress(f'FAIL task {task["task_id"]}: {exc or type(exc).__name__}')
                if isinstance(exc, TrafficExecutionError) and exc.can_continue:
                    failed_tasks.append(task['task_id'])
                    progress('Traffic cleanup confirmed; continuing to the next task')
                    continue
                raise
            persist(run_dir, status)
            progress(f'DONE task {task["task_id"]}')
        if failed_tasks:
            progress('Run finished: failed tasks: ' + ', '.join(failed_tasks))
            raise RuntimeError('Run finished with failed tasks: ' + ', '.join(failed_tasks))
        if args.stage == 'all':
            with stage('Result parsing'):
                parse_results(run_dir, status)
            with stage('Plotting'):
                from experiments.dcn_workload.scripts.plot import plot_results
                plot_results(run_dir)
            progress(f'Plotting complete: {run_dir / "figures"}')
        progress(f'Run complete: {run_dir}')



def run_ai(args):
    """Shared lock, task/attempt state, recovery and offline stages for AI."""
    from framework.config import load_deployment
    from experiments.ai_workload.scripts import run as ai
    from experiments.ai_workload.scripts.parse import parse_results as parse_ai
    from experiments.ai_workload.scripts.plot import plot_results as plot_ai
    run_dir = ROOT / 'results/ai_workload' / args.run_id
    if args.stage in ('status', 'parse', 'plot') and not args.dry_run:
        status = json.loads((run_dir / 'status.json').read_text()) if (run_dir / 'status.json').exists() else {'tasks': {}}
        if args.stage == 'status':
            print(json.dumps(status, indent=2))
        elif args.stage == 'parse':
            parse_ai(run_dir, status)
        else:
            plot_ai(run_dir)
        return
    deployment = load_deployment(args.deployment)
    selected = ai.specifications(args, deployment)
    networks = {name: index for index, name in enumerate(dict.fromkeys(s['network_id'] for s in selected))}
    selected.sort(key=lambda spec: networks[spec['network_id']])
    plan = [(spec, repeat) for spec in selected for repeat in range(1, args.repeat + 1)]
    if args.dry_run:
        print(json.dumps(dict(stage=args.stage, tasks=[dict(task_id=f'{s["id"]}-r{r:03d}',
                         spec=s, rankfile=ai.merged_rankfile(s), command=ai.mpi_command(s, deployment['mpi'],
                         '/REMOTE/ATTEMPT', '/REMOTE/BUILD/' + ai.BINARIES[s['workload']], 'PROBED'))
                         for s, r in plan]), indent=2))
        return
    os.environ['PERFTEST_COMMIT'] = perftest_commit()
    os.environ['ARTIFACT_RUN_ID'] = args.run_id
    intervals = {}
    for spec in selected:
        effective = experiment_deployment(deployment, spec)
        for remote in ai.remote_helpers(spec, effective).values():
            interval = effective['mpi'].get('ssh_interval_seconds', 0.2)
            intervals[remote.target] = max(intervals.get(remote.target, 0), interval)
        _, _, _, switches, _ = validate(spec)
        for name, switch in switches.items():
            target = switch.get('user', effective['tofino']['user']) + '@' + switch.get('management', name)
            interval = effective['tofino'].get('ssh_interval_seconds', 2)
            intervals[target] = max(intervals.get(target, 0), interval)
    with device_lock(), ssh_spacing(targets=intervals):
        print('AI SSH pacing: per-host intervals, compute nodes 0.2s and switches 2s by default.', flush=True)
        status_path = run_dir / 'status.json'
        if status_path.exists() and not args.resume:
            raise ValueError('run-id already exists; use --resume or a new run-id')
        run_dir.mkdir(parents=True, exist_ok=True)
        status = json.loads(status_path.read_text()) if status_path.exists() else dict(run_id=args.run_id, experiment='ai_workload', tasks={})
        built = set()
        shared = dict(selected=selected, deployment=deployment, run_dir=run_dir,
                      refreshed=set() if args.refresh_environment else None)
        if args.stage in ('prepare', 'check'):
            for spec in selected:
                effective = experiment_deployment(deployment, spec)
                if args.stage == 'prepare':
                    directory = run_dir / 'preparation' / spec['id']
                    directory.mkdir(parents=True, exist_ok=True)
                    report, _, _ = ai.prepare(spec, effective, directory, args.refresh_environment, shared)
                    atomic_json(run_dir / 'environment.json', report)
                else:
                    task = dict(task_id=spec['id'] + '-check', repeat=1)
                    ai.run_task(spec, effective, task, run_dir, None, built, stage='check',
                                refresh=args.refresh_environment, shared=shared)
            return
        wanted = {f'{s["id"]}-r{r:03d}' for s, r in plan}
        if status['tasks'] and set(status['tasks']) != wanted:
            raise ValueError('Resume task selection mismatch; use the original workload/mode/repeat selection')
        for spec, repeat in plan:
            key = f'{spec["id"]}-r{repeat:03d}'
            hashed = ai.identity(spec, experiment_deployment(deployment, spec), repeat)
            old = status['tasks'].get(key)
            if old and old['input_hash'] != hashed:
                raise ValueError('Resume configuration/source/dependency mismatch: ' + key)
            if old and old['status'] == 'completed' and not intact(old, run_dir):
                raise ValueError('Resume result checksum mismatch: ' + key)
            status['tasks'].setdefault(key, dict(task_id=key, experiment=spec['id'], repeat=repeat,
                                                input_hash=hashed, status='pending'))
        persist(run_dir, status)
        if args.resume:
            from framework.environment import check_agent
            check_agent(deployment['ssh']['expected_fingerprints'])
            for spec, repeat in plan:
                task = status['tasks'][f'{spec["id"]}-r{repeat:03d}']
                if task['status'] == 'completed':
                    ai.validate_resume_environment(spec, experiment_deployment(deployment, spec),
                                                   run_dir / task['attempt'])
            recover_processes(run_dir)
        atomic_json(run_dir / 'versions.json', dict(project=os.environ.get('PROJECT_VERSION', 'local-working-tree'),
                    image=os.environ.get('ARTIFACT_IMAGE_ID', 'native'), perftest=perftest_commit()))
        for number, (spec, repeat) in enumerate(plan, 1):
            task = status['tasks'][f'{spec["id"]}-r{repeat:03d}']
            if args.resume and task['status'] == 'completed':
                progress('Resume: verified completed task ' + task['task_id'])
                continue
            progress(f'AI task {number}/{len(plan)}: {task["task_id"]}')
            task.update(started=time.time(), exit_code=None, error=None)
            try:
                ai.run_task(spec, experiment_deployment(deployment, spec), task, run_dir, status,
                            built, refresh=args.refresh_environment, shared=shared)
            except BaseException as error:
                task.update(status='failed', exit_code=1, error=str(error), finished=time.time())
                persist(run_dir, status)
                raise
            task['finished'] = time.time()
            persist(run_dir, status)
        if args.stage == 'all':
            parse_ai(run_dir, status)
            plot_ai(run_dir)
        progress(f'Run complete: {run_dir}')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'artifact: {exc}', file=sys.stderr)
        sys.exit(1)

