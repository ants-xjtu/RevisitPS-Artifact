"""AI workload specification and execution, called by the shared task runner."""
from collections import Counter
import copy
import json
from pathlib import Path
import re
import shlex
import uuid

from framework.config import load_deployment
from framework.paths import REPO_ROOT as ROOT, resolve_repo_path
from framework.remote import RemoteRDMAHelper, logged_run, SSH_OPTIONS
from experiments.ai_workload.scripts.build import BINARIES


def specifications(args, deployment):
    from framework.runner import yaml_read, expand_experiments, validate
    registry = yaml_read(ROOT / 'experiments/ai_workload/experiment.yaml')
    site = yaml_read(resolve_repo_path(registry['groups']))
    inventory = yaml_read(resolve_repo_path(site['inventory']))['hosts']
    parameters = yaml_read(resolve_repo_path(registry['parameters']))
    for key in ('target_recv_bytes', 'iters'):
        if not isinstance(parameters[key], int) or parameters[key] < 1:
            raise ValueError(key + ' must be a positive integer')
    if not isinstance(parameters['warmup'], int) or parameters['warmup'] < 0:
        raise ValueError('warmup must be nonnegative')
    if site['bind_to'] != 'core':
        raise ValueError('This preset requires core binding')
    names = set()
    groups = []
    used = set()
    for group in site['groups']:
        group = copy.deepcopy(group)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', group['name']) or group['name'] in names:
            raise ValueError('Invalid/duplicate group name')
        names.add(group['name'])
        rankfile = resolve_repo_path(group['rankfile'])
        lines = [line.strip() for line in rankfile.read_text().splitlines() if line.strip()]
        ranks = [re.fullmatch(r'rank\s+(\d+)=(\S+)\s+slot=(\d+):(\d+)', line) for line in lines]
        if any(match is None for match in ranks):
            raise ValueError('Rankfile requires rank N=host slot=socket:core: ' + str(rankfile))
        ranks.sort(key=lambda match: int(match[1]))
        if [int(match[1]) for match in ranks] != list(range(group['np'])) or len(group['endpoints']) != group['np']:
            raise ValueError('Rank and endpoint counts must equal group np')
        if sorted(group['ring_order']) != list(range(group['np'])):
            raise ValueError('ring_order must be a permutation of group ranks')
        group['ranks'] = []
        for match, ip in zip(ranks, group['endpoints']):
            host = inventory[ip]
            if match[2] != host['hostname']:
                raise ValueError('Rankfile and deployment inventory disagree: ' + ip)
            cpu = (host['hostname'], int(match[3]), int(match[4]))
            if cpu in used:
                raise ValueError('Concurrent groups reuse a CPU core: ' + str(cpu))
            used.add(cpu)
            group['ranks'].append(dict(host=host['hostname'], slot=match[3] + ':' + match[4],
                                       endpoint=ip, device=host['mlx_device_name']))
        if group['ranks'][0]['host'] != deployment['mpi']['launcher']:
            raise ValueError('Every group rank 0 must be on mpi.launcher so CSVs have one owner')
        groups.append(group)
    if len(groups) != 2 or any(group['np'] != 8 for group in groups):
        raise ValueError('This preset preserves two concurrent groups of eight ranks')
    selected = []
    for workload in registry['workloads']:
        if args.workload not in ('all', workload):
            continue
        for network in expand_experiments(registry['experiments'], args.network_mode):
            validate(network)
            selected.append(dict(network, id=workload + '-' + network['id'], workload=workload,
                                 network_id=network['id'], network_mode=network['group'], groups=groups,
                                 parameters=parameters, bind_to=site['bind_to'], inventory=site['inventory']))
    if not selected:
        raise ValueError('No explicitly registered workload/network combination')
    return selected


def merged_rankfile(spec):
    lines = []; offset = 0
    for group in spec['groups']:
        for rank, row in enumerate(group['ranks']):
            lines.append(f"rank {offset + rank}={row['host']} slot={row['slot']}")
        offset += group['np']
    return '\n'.join(lines) + '\n'


def mpi_command(spec, mpi, remote_dir, binary, gid_index):
    ranks = [row for group in spec['groups'] for row in group['ranks']]
    counts = Counter(row['host'] for row in ranks)
    params = spec['parameters']; workload = spec['workload']
    command = [str(Path(mpi['prefix']) / 'bin/mpirun'), '--prefix', mpi['prefix'],
               '--host', ','.join(f'{host}:{count}' for host, count in counts.items()),
               '-np', str(len(ranks)), '--rankfile', remote_dir + '/configs/merged.rankfile',
               '--bind-to', spec['bind_to'], '--wdir', remote_dir,
               '-x', 'LD_LIBRARY_PATH', '-x', 'IB_DEV_MAP=' + ','.join(row['device'] for row in ranks),
               '-x', 'GID_INDEX=' + str(gid_index)]
    if workload != 'ring_allreduce':
        command += ['-x', 'USE_RDMA_CM=0']
    command += [binary, '--bench', 'latency' if workload == 'ring_allreduce' else 'jct', '--mode', 'write',
                '--sizes', str(params['target_recv_bytes'] // (spec['groups'][0]['np'] - 1)
                               if workload == 'alltoall' else params['target_recv_bytes']),
                '--warmup', str(params['warmup']), '--iters', str(params['iters']),
                '--group-nps', ','.join(str(group['np']) for group in spec['groups'])]
    csvs = '|'.join(remote_dir + '/raw/' + group['name'] + '.csv' for group in spec['groups'])
    if workload == 'ring_allreduce':
        command += ['--inflight', '1', '--sig-interval', str(params['ring_signal_interval']),
                    '--write-notify', params['ring_write_notify'], '--latency-metric', 'fct',
                    '--iter-barrier', '--write-chunk', params['ring_write_chunk'],
                    '--group-ring-orders', '|'.join(','.join(map(str, g['ring_order'])) for g in spec['groups']),
                    '--group-dump-iter-fct', csvs]
    else:
        command += ['--group-dump-csvs', csvs, '--iter-world-barrier', '--dump-fct']
        if workload == 'alltoallv':
            command += ['--traffic-pattern', 'zipfian_incast', '--zipf-alpha', str(params['zipf_alpha'])]
    return command


def identity(spec, deployment, repeat):
    from framework.runner import input_hash, canonical_hash, digest
    base = input_hash(spec, deployment, repeat)
    files = {str(p.relative_to(ROOT)): digest(p) for folder in
             ('experiments/ai_workload', 'framework', 'switches') for p in (ROOT / folder).rglob('*')
             if p.is_file() and p.suffix in ('.py', '.cpp', '.h', '.sh', '.p4', '.yaml', '.rankfile')
             and not {'__pycache__', 'reference_results'} & set(p.parts)}
    return canonical_hash(dict(base=base, sources=files, spec=spec, deployment=deployment))


def remote_helpers(spec, deployment):
    hosts = sorted({row['host'] for group in spec['groups'] for row in group['ranks']})
    from framework.runner import yaml_read
    inventory = yaml_read(resolve_repo_path(spec['inventory']))['hosts']
    users = {host: {entry.get('user', deployment['rdma']['user']) for entry in inventory.values()
                    if entry['hostname'] == host} for host in hosts}
    if any(len(value) != 1 for value in users.values()):
        raise ValueError('MPI requires one SSH user per host')
    if len({next(iter(value)) for value in users.values()}) != 1:
        raise ValueError('The MPI preset requires the same SSH user on every rank host')
    return {host: RemoteRDMAHelper(next(iter(users[host])), host) for host in hosts}


def preflight_launcher(spec, mpi, remotes):
    launcher = remotes[mpi['launcher']]
    q = shlex.quote
    # Do not forward the container's agent. The launcher needs its own credentials.
    for host, remote in remotes.items():
        launcher.ssh(shlex.join(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                '-o', 'ForwardAgent=no', '-o', 'ConnectTimeout=10', remote.target,
                                'true']), timeout=30)
    # Let Open MPI/hwloc validate logical socket/core indices in the actual environment.
    return launcher


def prepare(spec, deployment, directory, refresh=False, shared=None):
    from framework.environment import Environment
    from framework.environment_cache import prepare_environment
    from framework.runner import validate, atomic_json
    from experiments.ai_workload.scripts.build import target_environments, build, distribute
    _, _, hosts, switches, _ = validate(spec)
    environment = Environment(deployment, directory / 'environment.json')
    from framework.results import canonical_hash
    if shared is None:
        report = prepare_environment(environment, hosts, switches, ROOT / 'results/ai_workload', refresh=refresh)
        runtime_cache, build_cache = {}, {}
        common_key = None
    else:
        if 'batches' not in shared:
            from framework.check_cache import readiness_batches
            shared['batches'] = readiness_batches(shared['selected'], shared['deployment'])
        common_key, batch = next((key, batch) for key, batch in shared['batches'].items()
                                 if any(item['id'] == spec['id'] for item in batch['experiments']))
        common_path = shared['run_dir'] / 'checks/common' / common_key / 'environment.json'
        common_reports = shared.setdefault('common', {})
        if common_key not in common_reports:
            common = Environment(batch['deployment'], common_path)
            common_reports[common_key] = copy.deepcopy(prepare_environment(
                common, batch['hosts'], batch['switches'], shared['run_dir'].parent,
                refresh=refresh))
        report = copy.deepcopy(common_reports[common_key])
        report.pop('readiness_cache', None)
        report['shared_readiness'] = str(common_path)
        environment.report = report
        environment.save()
        runtime_cache = shared.setdefault('runtime', {})
        build_cache = shared.setdefault('builds', {})
    remotes = remote_helpers(spec, deployment)
    runtime_key = canonical_hash(dict(common=common_key, mpi=deployment['mpi'],
                                     groups=spec['groups'], bind_to=spec['bind_to'],
                                     targets={host: remote.target for host, remote in remotes.items()}))
    if runtime_key not in runtime_cache:
        environment.record(deployment['mpi']['launcher'], 'ai-launcher-ssh',
                           lambda: (preflight_launcher(spec, deployment['mpi'], remotes), 'passed')[1])
        targets = environment.record('mpi-nodes', 'ai-runtime-inventory',
                                     lambda: target_environments(deployment['mpi'], remotes))
        runtime_cache[runtime_key] = dict(targets=targets, source=str(environment.path))
    else:
        cached = runtime_cache[runtime_key]
        targets = cached['targets']
        environment.record('mpi-nodes', 'ai-runtime-reuse', lambda: dict(source=cached['source']))
    holder = {}
    def compile_and_distribute():
        cache, artifact = build(spec['workload'], deployment['mpi'], targets)
        holder['destination'] = distribute(cache, artifact, deployment['mpi'], remotes)
        holder['built'] = artifact
        return {'build_key': artifact['key'], 'binary_checksums': artifact['files']}
    build_key = (runtime_key, spec['workload'])
    if build_key not in build_cache:
        environment.record('mpi-nodes', 'ai-build-and-loader-probe', compile_and_distribute)
        build_cache[build_key] = dict(holder, source=str(environment.path))
    else:
        holder = build_cache[build_key]
        environment.record('mpi-nodes', 'ai-build-reuse', lambda: dict(source=holder['source']))
    destination, built = holder['destination'], holder['built']
    report['ai'] = dict(build=built, targets=targets, launcher=deployment['mpi']['launcher'],
                        status='prepared', note='RDMA and CPU binding acceptance requires the check/run smoke test')
    atomic_json(directory / 'environment.json', report)
    return report, remotes, destination


def configure_hardware(spec, deployment, attempt, report, built, run_id, shared=None):
    from framework.runner import snapshot, prepare_runtime
    from framework.rdma.run_test import load_endpoints
    from framework.rdma.config_nic import configure
    from switches.scripts.config_sw import run_switch_config
    runtime, _, _, _ = snapshot(spec, deployment, 1, attempt)
    parser = prepare_runtime(runtime, report, attempt, run_id, spec['id'], deployment)
    cache = shared.setdefault('hardware', {}) if shared is not None else {}
    run_switch_config(parser, do_build=True, do_run=True, do_config=True, built=built,
                      reuse=cache.setdefault('switches', {}))
    hosts, _, helpers = load_endpoints(parser, discovery_cache=cache.setdefault('discovery', {}))
    configure(hosts, helpers, deployment, spec['network_mode'] == 'lossless',
              firmware_cache=cache.setdefault('firmware', {}))
    gids = {helpers[row['endpoint']].gid for g in spec['groups'] for row in g['ranks']}
    if None in gids or len(gids) != 1:
        raise ValueError('The current MPI programs require a common probed RoCE v2 GID index')
    return gids.pop()


def execute(spec, mpi, attempt, remotes, binary_dir, remote_dir, gid, timeout):
    from framework.runner import atomic_json, digest
    from experiments.ai_workload.scripts.parse import samples
    q = shlex.quote
    configs = attempt / 'configs'; configs.mkdir(parents=True, exist_ok=True)
    raw = attempt / 'raw'; raw.mkdir(exist_ok=True)
    logs = attempt / 'logs'; logs.mkdir(exist_ok=True)
    atomic_json(configs / 'ai.json', spec)
    (configs / 'merged.rankfile').write_text(merged_rankfile(spec))
    token = uuid.uuid4().hex
    binary = binary_dir + '/' + BINARIES[spec['workload']]
    wrapper = configs / 'rank.sh'
    wrapper.write_text('#!/bin/bash\nset -euo pipefail\ntest "$(ulimit -l)" = unlimited\n' +
        'state=' + q(remote_dir + '/ranks/rank-') + '${OMPI_COMM_WORLD_RANK:?}\n' +
        'echo "$$ $(awk \'{print $22}\' /proc/$$/stat)" > "$state.pid"\n' +
        'exec env ARTIFACT_PROCESS_TOKEN=' + q(token) + ' ' + q(binary) + ' "$@"\n')
    wrapper.chmod(0o755)
    command = mpi_command(spec, mpi, remote_dir, remote_dir + '/configs/rank.sh', gid)
    atomic_json(configs / 'command.json', command)
    rank_procs = []
    for host, remote in remotes.items():
        # Never accept leftover CSVs when local state was removed or copied.
        # The parent may already exist because the smoke test has its own child.
        prepare = ('test ! -e ' + q(remote_dir + '/raw') + ' && mkdir -p ' +
                   ' '.join(q(remote_dir + '/' + x) for x in ('raw', 'logs', 'ranks')))
        remote.upload_verified_directory(configs, remote_dir + '/configs', prepare)
    for rank, row in enumerate(row for group in spec['groups'] for row in group['ranks']):
        proc = dict(state=remote_dir + f'/ranks/rank-{rank}', token=token, target=remotes[row['host']].target,
                    process_group=False, log=remote_dir + '/logs/mpi.log')
        rank_procs.append((remotes[row['host']], proc))
        with Path(__import__('os').environ.get('ARTIFACT_PROCESS_JOURNAL', str(attempt / 'processes.jsonl'))).open('a') as stream:
            stream.write(json.dumps(proc) + '\n')
    launcher = remotes[mpi['launcher']]
    environment = ('export PATH=' + q(mpi['prefix'] + '/bin') + ':"$PATH"; '
                   'export LD_LIBRARY_PATH=' + q(mpi['library_path']) + '${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; ')
    proc = None
    processes = getattr(launcher, 'processes', [])
    started_before = len(processes) if isinstance(processes, list) else 0
    failed = False
    collected = False
    try:
        # This launch uses the full rankfile but does not open RDMA queues.
        bind_check = command[:command.index('-x')] + ['--report-bindings', '/bin/true']
        (logs / 'binding.log').write_text(launcher.ssh(environment + shlex.join(bind_check), timeout=60).stdout)
        proc = launcher.start(environment + shlex.join(command), remote_dir + '/logs/mpi.log')
        launcher.wait(proc, timeout)
        launcher.collect_files(remote_dir,
                               ['raw/' + group['name'] + '.csv' for group in spec['groups']] + ['logs/mpi.log'],
                               attempt)
        collected = True
        for group in spec['groups']:
            samples(raw / (group['name'] + '.csv'), spec['parameters']['iters'])
    except BaseException:
        failed = True
        # start() journals ownership before SSH. It may have launched the process
        # even if SSH/PID acknowledgement fails before returning its handle.
        if proc is None and isinstance(processes, list) and len(processes) > started_before:
            proc = processes[-1]
        raise
    finally:
        cleanup_errors = []
        if proc is not None:
            try:
                if not collected:
                    launcher.sync_remote_to_local(proc['log'], logs / 'mpi.log')
            except Exception as error:
                cleanup_errors.append(str(error))
            try:
                launcher.stop(proc)
            except Exception as error:
                cleanup_errors.append(str(error))
        cleanup_hosts = {}
        for remote, rank_proc in rank_procs:
            cleanup_hosts.setdefault(remote.target, (remote, []))[1].append(rank_proc)
        for remote, processes in cleanup_hosts.values():
            try:
                remote.stop_many(processes)
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            atomic_json(logs / 'cleanup-errors.json', cleanup_errors)
            if not failed:
                raise RuntimeError('MPI cleanup/log collection failed: ' + '; '.join(cleanup_errors))
    return {str(p.relative_to(attempt)): digest(p) for folder in (raw, configs, logs)
            for p in folder.rglob('*') if p.is_file()}


def smoke_identity(spec, deployment, report, gid):
    from framework.check_cache import traffic_identity
    from framework.results import digest
    base = traffic_identity(spec, deployment)
    sources = {str(p.relative_to(ROOT)): digest(p)
               for p in (ROOT / 'experiments/ai_workload').rglob('*')
               if p.is_file() and p.suffix in ('.py', '.cpp', '.h', '.hpp')}
    return dict(policy='ai-workload-algorithm-smoke-v1', network=base,
                workload=spec['workload'], groups=spec['groups'], bind_to=spec['bind_to'],
                parameters=spec['parameters'], mpi=deployment['mpi'], gid=gid,
                build=report['ai']['build'], targets=report['ai']['targets'], sources=sources)


def run_task(spec, deployment, task, run_dir, state, built, stage='run', refresh=False, shared=None):
    import os
    from framework.runner import atomic_json, persist
    directory = run_dir / ('checks' if stage == 'check' else 'tasks') / task['task_id']
    attempt = directory / f'attempt-{len(list(directory.glob("attempt-*"))) + 1:03d}'
    attempt.mkdir(parents=True)
    task.update(status='running', attempt=str(attempt.relative_to(run_dir)))
    if state is not None:
        persist(run_dir, state)
    os.environ.update(ARTIFACT_COMMAND_LOG=str(attempt / 'commands.log'),
                      ARTIFACT_PROCESS_JOURNAL=str(attempt / 'processes.jsonl'),
                      ARTIFACT_SWITCH_LOG=str(run_dir / 'checks/switches'))
    report, remotes, binary_dir = prepare(spec, deployment, attempt, refresh, shared)
    gid = configure_hardware(spec, deployment, attempt, report, built, run_dir.name, shared)
    remote_dir = deployment['mpi']['remote_root'].rstrip('/') + '/' + run_dir.name + '/' + task['task_id'] + '/' + attempt.name
    short = copy.deepcopy(spec)
    short['parameters'].update(warmup=1, iters=deployment['mpi']['smoke_iters'],
                               target_recv_bytes=deployment['mpi']['smoke_bytes'])
    from framework.environment import Environment
    from framework.check_cache import traffic_once
    environment = Environment(deployment, attempt / 'environment.json')
    environment.report = report
    def smoke():
        environment.record(spec['id'], 'ai-rdma-smoke', lambda:
            execute(short, deployment['mpi'], attempt / 'smoke', remotes, binary_dir,
                    remote_dir + '/smoke', gid, 120))
    evidence = traffic_once(spec, deployment, run_dir, attempt, environment, smoke,
                            shared['refreshed'] if shared is not None else (set() if refresh else None),
                            identity=smoke_identity(short, deployment, report, gid),
                            evidence_dir=attempt / 'smoke')
    report['ai'].update(status='passed', gid_index=gid,
                        cpu_binding='reused' if evidence['reused'] else 'passed',
                        rdma_smoke='reused' if evidence['reused'] else 'passed',
                        traffic_evidence=evidence)
    atomic_json(run_dir / 'environment.json', report)
    atomic_json(attempt / 'environment.json', report)
    if stage == 'check':
        task.update(status='completed', exit_code=0)
        return
    task['files'] = execute(spec, deployment['mpi'], attempt, remotes, binary_dir,
                            remote_dir, gid, deployment['mpi']['timeout_seconds'])
    from framework.runner import digest
    task['files']['environment.json'] = digest(attempt / 'environment.json')
    task.update(status='completed', exit_code=0)


def validate_resume_environment(spec, deployment, attempt):
    """Data reuse requires the same actual target and controller dependency identities."""
    from experiments.ai_workload.scripts.build import target_environments, toolchain_identity
    report = json.loads((attempt / 'environment.json').read_text())['ai']
    saved = report['build']['identity']
    remotes = remote_helpers(spec, deployment)
    targets = target_environments(deployment['mpi'], remotes)
    if targets != saved['targets'] or toolchain_identity(deployment['mpi']) != saved['toolchain']:
        raise ValueError('Resume MPI/CPU/runtime dependency mismatch; use a new run-id')
