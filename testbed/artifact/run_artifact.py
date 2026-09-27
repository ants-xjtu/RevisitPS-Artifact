#!/usr/bin/env python3
"""Single-server artifact orchestration. No hardware access in --dry-run."""
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
for path in (ROOT / 'utils', ROOT / 'scripts', ROOT, ROOT.parent / 'plot'):
    sys.path.insert(0, str(path))
import yaml
from artifact.environment import Environment, CheckFailed, check_summary
from common.remote_rdma_helper import RemoteRDMAHelper, logged_run, ssh_spacing
from common.progress import progress, stage
from conf_parser.yaml_parser import TestConfParser


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
    from conf_parser.yaml_parser import SwitchConfParser
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
    sources = {str(p.relative_to(ROOT)): digest(p) for folder in ('src', 'utils', 'scripts', 'artifact')
               for p in (ROOT / folder).rglob('*.py') if '__pycache__' not in p.parts and 'results' not in p.parts}
    sources.update({str(p.relative_to(ROOT)): digest(p) for p in (ROOT / 'src').rglob('*.p4')})
    return canonical_hash(dict(experiment=experiment, deployment=deployment, repeat=repeat,
                               config=config, references={k: digest(v) for k, v in refs.items()}, sources=sources,
                               perftest=perftest_commit()))


def perftest_commit():
    if os.environ.get('PERFTEST_COMMIT'):
        return os.environ['PERFTEST_COMMIT']
    source = ROOT / 'third_party/perftest'
    commit = logged_run(['git', '-C', str(source), 'rev-parse', 'HEAD']).stdout.strip()
    entry = logged_run(['git', '-C', str(ROOT.parent), 'ls-files', '-s', 'testbed/third_party/perftest']).stdout.split()
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
        'config': sde + " --command 'export PYTHONPATH=$PYTHONPATH:utils; python3 {{cp_script_path}} --hostname {{hostname}} --topo {{topo}} --switches {{switches}} --hosts {{hosts}} --bfrt-port {{port}}'"}
    return save_runtime(runtime, attempt)


def recover_processes(run_dir):
    for journal in sorted(run_dir.glob('tasks/*/attempt-*/processes.jsonl')):
        for line in journal.read_text().splitlines():
            proc = json.loads(line)
            user, hostname = proc['target'].split('@', 1)
            RemoteRDMAHelper(user, hostname).stop(proc)


def trace_inputs(runtime, parser, run_dir):
    from trace.gen_trace import gen_trace_from_host, gen_trace_from_connection
    from trace.sync_trace import validate_trace, sync_trace
    spec = runtime['artifact']['experiment']
    gen = runtime['applications']['gen_trace']
    links = yaml_read(runtime['config']['connections'])['connections']
    key = canonical_hash({k: gen[k] for k in ('load', 'bandwidth', 'time', 'seed')} |
                         {'cdf': digest(gen['cdf']), 'connections': links, 'mode': spec['trace_mode']})
    folder = run_dir / 'traces' / key
    gen['local_path'] = str(folder)
    parser.get().applications.gen_trace.local_path = str(folder)
    with stage('Trace generation and input validation'):
        if not folder.exists():
            command = gen_trace_from_host if spec['trace_mode'] == 'host' else gen_trace_from_connection
            command.callback(parser)
        else:
            progress('Trace cache found; reusing and validating inputs')
        hashes = {}
        for link in links:
            name = f"{link['sender']}-{link['receiver']}.trace"
            sizes = validate_trace(folder / name)
            if max(sizes) > runtime['applications']['remote_rdma']['test']['cmd']['config']['msg_size']:
                raise ValueError('Trace message exceeds configured perftest allocation')
            hashes[name] = digest(folder / name)
    with stage('Trace synchronization and remote checksum verification'):
        sync_trace.callback(parser)
    return hashes


def collect_and_validate(attempt, runtime, links):
    from plot.analysis_fct import parse_fct
    from plot.plot_throughput import read_intervals, window_average
    from trace.sync_trace import validate_trace
    files = {}
    for link in links:
        stem = f"{link['sender']}-{link['receiver']}"
        for role in ('sender', 'receiver'):
            path = attempt / 'raw' / (stem + '.' + role + '.log')
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f'Missing/empty endpoint log: {path}')
        if runtime['artifact']['experiment']['traffic'] == 'trace':
            path = attempt / 'raw' / (stem + '.sender.log.csv')
            sizes = validate_trace(Path(runtime['applications']['gen_trace']['local_path']) / (stem + '.trace'))
            _, counts = parse_fct(path, sizes)
            atomic_json(attempt / 'raw' / (stem + '.validation.json'), counts)
            if any(counts[key] for key in ('incomplete', 'nonpositive', 'malformed')) or counts['valid'] != len(sizes):
                raise ValueError(f'Incomplete/invalid FCT data: {path}: {counts}')
        else:
            rows = read_intervals(attempt / 'raw' / (stem + '.sender.log'))
            measurement = runtime['artifact']['measurement']
            window_average(rows, measurement['warmup_seconds'], measurement['warmup_seconds'] + measurement['duration_seconds'])
    for path in list((attempt / 'raw').iterdir()) + list((attempt / 'configs').iterdir()):
        if path.is_file():
            files[str(path.relative_to(attempt))] = digest(path)
    return files


def intact(task, run_dir):
    attempt = run_dir / task['attempt']
    if not task.get('files') or not all((attempt / p).is_file() and digest(attempt / p) == checksum for p, checksum in task['files'].items()):
        return False
    if task.get('trace_hashes'):
        runtime = yaml_read(attempt / 'configs/runtime.yaml')
        trace_dir = Path(runtime['applications']['gen_trace']['local_path'])
        return all((trace_dir / name).is_file() and digest(trace_dir / name) == checksum for name, checksum in task['trace_hashes'].items())
    return True


def manifest(run_dir, status):
    target = run_dir / 'manifest.csv'
    tmp = target.with_suffix('.tmp')
    fields = ['task_id', 'experiment', 'repeat', 'status', 'input_hash', 'attempt', 'started', 'finished', 'exit_code', 'error']
    with tmp.open('w') as output:
        writer = csv.DictWriter(output, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(status['tasks'].values())
    tmp.replace(target)


def persist(run_dir, status):
    atomic_json(run_dir / 'status.json', status)
    manifest(run_dir, status)


@contextlib.contextmanager
def device_lock():
    folder = Path(os.environ.get('ARTIFACT_LOCK_DIR', ROOT / 'artifact/locks'))
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'testbed.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('The testbed is already held by another local artifact process')
        yield


def check_experiment_traffic(experiment, deployment, run_dir, environment, built):
    """Active check: deploy the selected fabric, then validate both directions."""
    from remote_rdma.run_test import load_endpoints
    from remote_rdma.config_nic import configure
    from remote_rdma.check_link import check_links, verify_trace_support
    from remote_tofino.config_sw import run_switch_config
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
        environment.record(experiment['id'], 'bidirectional-throughput', lambda: check_links(parser))
        environment.record(experiment['id'], 'trace-format', lambda:
            verify_trace_support(parser, connections, helpers, attempt / 'checks/trace-smoke'))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.copy2(environment.path, attempt / 'environment.json')


def run_task(experiment, deployment, repeat, task, run_dir, resume=False, built=None, state=None, refresh_environment=False):
    from artifact.environment_cache import prepare_environment
    from remote_rdma.run_test import load_endpoints, execute_connections
    from remote_rdma.config_nic import configure
    from remote_tofino.config_sw import run_switch_config
    old = copy.deepcopy(task)
    directory = run_dir / 'tasks' / task['task_id']
    index = len(list(directory.glob('attempt-*'))) + 1
    attempt = directory / f'attempt-{index:03d}'
    attempt.mkdir(parents=True)
    os.environ.update(ARTIFACT_COMMAND_LOG=str(attempt / 'commands.log'),
                      ARTIFACT_PROCESS_JOURNAL=str(attempt / 'processes.jsonl'),
                      ARTIFACT_SWITCH_LOG=str(run_dir / 'checks/switches'))
    runtime, hosts, switches, links = snapshot(experiment, deployment, repeat, attempt)
    task.update(status='running', started=time.time(), attempt=str(attempt.relative_to(run_dir)), exit_code=None, error=None)
    atomic_json(run_dir / 'checks' / (task['task_id'] + '.json'), {'stage': 'prepare', 'attempt': task['attempt']})
    if state is not None:
        persist(run_dir, state)
    with stage('Environment preparation'):
        report = prepare_environment(Environment(deployment, run_dir / 'environment.json'),
                                     hosts, switches, run_dir.parent, refresh=refresh_environment)
    shutil.copy2(run_dir / 'environment.json', attempt / 'environment.json')
    parser = prepare_runtime(runtime, report, attempt, run_dir.name, task['task_id'], deployment)
    # Apply the selected fabric/NIC settings; traffic acceptance belongs to check.
    run_switch_config(parser, do_build=True, do_run=True, do_config=True, built=built)
    with stage('NIC discovery, configuration and readback'):
        host_parser, connections, helpers = load_endpoints(parser)
        configure(host_parser, helpers, deployment, 'lossless' in experiment['group'])
    if resume and old.get('status') == 'completed' and intact(old, run_dir):
        task.update(old)
        task['revalidated'] = time.time()
        progress('Resume: completed data verified; skipping traffic')
        return
    if experiment['traffic'] == 'trace':
        task['trace_hashes'] = trace_inputs(runtime, parser, run_dir)
        save_runtime(runtime, attempt)
    with stage('Pre-traffic counters'):
        for ip, helper in helpers.items():
            (attempt / 'counters').mkdir(exist_ok=True)
            (attempt / 'counters' / (ip + '.before')).write_text(helper.get_counter())
    conf = parser.get().applications.remote_rdma.test
    execute_connections(parser, connections, helpers, duration=conf.cmd.timeout if experiment['traffic'] == 'bandwidth' else None)
    with stage('Collected data validation'):
        task['files'] = collect_and_validate(attempt, runtime, links)
    task.update(status='completed', finished=time.time(), exit_code=0)


def parse_results(run_dir, status):
    from plot.analysis_fct import parse_fct, summarize
    from plot.figure2_data import summarize_size_buckets
    from plot.plot_throughput import read_intervals, aggregate_windows
    output = run_dir / 'parsed'
    output.mkdir(exist_ok=True)
    summaries, throughput, size_buckets = [], [], []
    if not any(task['status'] == 'completed' for task in status['tasks'].values()):
        raise ValueError('No completed tasks to parse')
    for task in status['tasks'].values():
        if task['status'] != 'completed':
            continue
        if not intact(task, run_dir):
            raise ValueError(f'Data integrity failure: {task["task_id"]}')
        attempt = run_dir / task['attempt']
        runtime = yaml_read(attempt / 'configs/runtime.yaml')
        spec = runtime['artifact']['experiment']
        common = dict(task_id=task['task_id'], experiment=spec['id'], group=spec['group'],
                      algorithm=spec['algorithm'], repeat=task['repeat'])
        if spec['metric'] == 'fct':
            records = []
            for path in sorted((attempt / 'raw').glob('*.sender.log.csv')):
                rows, counts = parse_fct(path)
                if any(counts[key] for key in ('incomplete', 'nonpositive', 'malformed')):
                    raise ValueError(f'Invalid FCT: {path}')
                records.extend(rows)
            if not records:
                raise ValueError('No FCT samples')
            for row in summarize(records):
                summaries.append(common | row)
            if spec["group"] in ("lossless", "lossy"):
                for row in summarize_size_buckets(records):
                    size_buckets.append(common | row)
        else:
            series = [read_intervals(path) for path in sorted((attempt / 'raw').glob('*.sender.log'))]
            measurement = runtime['artifact']['measurement']
            # Starts are coordinated but not strictly simultaneous. Preserve measured
            # launch offsets in the common orchestrator time axis.
            starts = json.loads((attempt / 'raw/starts.json').read_text())
            origin = min(item['started'] for item in starts)
            offsets = {item['connection']: item['started'] - origin for item in starts}
            paths = sorted((attempt / 'raw').glob('*.sender.log'))
            for path, rows in zip(paths, series):
                offset = offsets[path.name]
                for row in rows:
                    row['start'] += offset
                    row['end'] += offset
            begin = max(offsets.values()) + measurement['warmup_seconds']
            end = min(rows[-1]['end'] for rows in series)
            for row in aggregate_windows(series, begin, end):
                throughput.append(common | row)
    atomic_json(output / 'figure2-buckets.json', size_buckets)
    atomic_json(output / 'fct.json', summaries)
    atomic_json(output / 'throughput.json', throughput)
    for name, rows in [('fct', summaries), ('throughput', throughput), ('figure2-buckets', size_buckets)]:
        if rows:
            with (output / (name + '.csv')).open('w') as stream:
                writer = csv.DictWriter(stream, list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)


def main(argv=None):
    from artifact.environment_cache import prepare_environment
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', default='all', help='lossless, lossy, or all')
    parser.add_argument('--stage', choices=['check', 'prepare', 'run', 'status', 'parse', 'plot', 'all'], default='all')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--refresh-environment', action='store_true',
                        help='Run environment checks again instead of reusing the latest matching passed report')
    parser.add_argument('--deployment', type=Path, default=ROOT / 'conf/deployment.yaml')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id) or args.repeat < 1:
        parser.error('run-id must contain only letters/digits/_/- and repeat must be positive')
    os.chdir(ROOT)
    run_dir = ROOT / 'artifact/results' / args.run_id
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
                from plot.plot_artifact import plot_results
                plot_results(run_dir)
            progress(f'Plotting complete: {run_dir / "figures"}')
        return
    deployment = yaml_read(args.deployment)
    measure = deployment['measurement']
    if measure['threshold_gbps'] < 90 or measure['duration_seconds'] <= 0 or measure['warmup_seconds'] < 0 or measure['interval_seconds'] < 1:
        raise ValueError('Require threshold >=90 Gbps and a valid fixed measurement window')
    registry = yaml_read(ROOT / 'artifact/experiments.yaml')['experiments']
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
    with device_lock(), ssh_spacing(1 if args.stage == 'check' else 0):
        run_dir.mkdir(parents=True, exist_ok=True)
        os.environ['ARTIFACT_COMMAND_LOG'] = str(run_dir / 'checks/commands.log')
        if args.stage in ('check', 'prepare'):
            if args.stage == 'check':
                print('SSH pacing: at least 1 second between remote requests (all hosts).', flush=True)
            combined = {'checks': [], 'experiments': {}}
            built = set()
            for experiment_number, experiment in enumerate(selected, 1):
                print(f"[{args.stage}] Experiment {experiment_number}/{len(selected)}: {experiment['id']}", flush=True)
                _, _, hosts, switches, _ = validate(experiment)
                if args.stage == 'prepare':
                    prepare_environment(
                        Environment(experiment_deployment(deployment, experiment), run_dir / 'environment.json'),
                        hosts, switches, run_dir.parent, refresh=True)
                    continue
                report_path = run_dir / 'checks' / experiment['id'] / 'environment.json'
                environment = Environment(experiment_deployment(deployment, experiment), report_path)
                try:
                    prepare_environment(environment, hosts, switches, run_dir.parent, refresh=True, prepare=False)
                except CheckFailed:
                    pass  # Keep collecting readiness failures for all experiments.
                else:
                    try:
                        environment.record(experiment['id'], 'active-validation', lambda:
                            check_experiment_traffic(experiment, experiment_deployment(deployment, experiment),
                                                     run_dir, environment, built))
                    except Exception:
                        pass  # Failure is recorded; inspect remaining experiments.
                combined['experiments'][experiment['id']] = environment.report
                combined['checks'].extend(dict(item, experiment=experiment['id'])
                                          for item in environment.report['checks'])
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
            from artifact.environment import check_agent
            check_agent(deployment['ssh']['expected_fingerprints'])
            recover_processes(run_dir)
        atomic_json(run_dir / 'versions.json', {'project': os.environ.get('PROJECT_VERSION', 'local-working-tree'),
                    'image': os.environ.get('ARTIFACT_IMAGE_ID', 'native'), 'perftest': perftest_commit()})
        config_dir = run_dir / 'configs'
        if not config_dir.exists():
            shutil.copytree(ROOT / 'conf', config_dir)
            shutil.copytree(ROOT / 'src', config_dir / 'source')
            for folder in ('utils', 'scripts'):
                shutil.copytree(ROOT / folder, config_dir / 'implementation' / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (config_dir / 'implementation/artifact').mkdir(parents=True)
            for file in (ROOT / 'artifact').glob('*.py'):
                shutil.copy2(file, config_dir / 'implementation/artifact' / file.name)
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
                         args.resume, built, status, refresh_environment=args.refresh_environment)
            except BaseException as exc:
                task.update(status='failed', finished=time.time(), exit_code=1, error=str(exc))
                persist(run_dir, status)
                progress(f'FAIL task {task["task_id"]}: {exc or type(exc).__name__}')
                raise
            persist(run_dir, status)
            progress(f'DONE task {task["task_id"]}')
        if args.stage == 'all':
            with stage('Result parsing'):
                parse_results(run_dir, status)
            with stage('Plotting'):
                from plot.plot_artifact import plot_results
                plot_results(run_dir)
            progress(f'Plotting complete: {run_dir / "figures"}')
        progress(f'Run complete: {run_dir}')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'artifact: {exc}', file=sys.stderr)
        sys.exit(1)
