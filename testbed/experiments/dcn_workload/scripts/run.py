"""DCN trace, measurement and collection implementation; orchestration is shared."""
import copy
import json
import os
from pathlib import Path
import shutil
import time
from framework.progress import stage, progress

def trace_inputs(runtime, parser, run_dir):
    from framework.runner import canonical_hash, digest, yaml_read
    from experiments.dcn_workload.scripts.generate_trace import gen_trace_from_host, gen_trace_from_connection
    from experiments.dcn_workload.scripts.sync_trace import validate_trace, sync_trace
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
    from framework.runner import atomic_json, digest
    from experiments.dcn_workload.scripts.parse import parse_fct
    from experiments.dcn_workload.scripts.plot_throughput import read_intervals, window_average
    from experiments.dcn_workload.scripts.sync_trace import validate_trace
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
            _, counts = parse_fct(path, sizes, raw_timestamps=True)
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


def run_task(experiment, deployment, repeat, task, run_dir, resume=False, built=None, state=None, refresh_environment=False):
    from framework.runner import (atomic_json, snapshot, prepare_runtime, persist, Environment,
                                  intact, save_runtime, trace_inputs, collect_and_validate)
    from framework.environment_cache import prepare_environment
    from framework.rdma.run_test import load_endpoints, execute_connections
    from framework.rdma.config_nic import configure
    from switches.scripts.config_sw import run_switch_config
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


