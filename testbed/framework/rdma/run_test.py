"""Start every receiver before coordinating senders; retain both ends on failure."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import yaml
from pathlib import Path
import shlex
import time

import click
from jinja2 import Environment, StrictUndefined
from framework.conf_parser.yaml_parser import HostConfParser, ConnectionConfParser
from framework.remote import generate_ip_helper_map, ssh_spacing, SSHConnectionError
from framework.progress import progress
from framework.rdma.nic_batch import collect_counters


class TrafficExecutionError(RuntimeError):
    """A traffic failure with an explicit decision about subsequent tasks."""
    def __init__(self, message, *, can_continue):
        super().__init__(message)
        self.can_continue = can_continue


def verify_traffic_stopped(helpers):
    # Verify launch intents too: a failed SSH launch may have created processes
    # without returning handles or writing their PID files.
    groups = {}
    for helper in helpers.values():
        group = groups.setdefault(helper.target, (helper, set()))
        group[1].update(proc['token'] for proc in helper.processes)
    script = """import os, pathlib, sys
wanted = {('ARTIFACT_PROCESS_TOKEN=' + token).encode() for token in sys.argv[1:]}
alive = []
for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        env = (proc / 'environ').read_bytes().split(bytes([0]))
        if wanted.intersection(env):
            alive.append(proc.name)
    except (FileNotFoundError, ProcessLookupError):
        continue
if alive:
    raise SystemExit('Owned traffic processes still alive: ' + ', '.join(alive))
"""
    for helper, tokens in groups.values():
        if tokens:
            helper.ssh('sudo -n python3 -c ' + shlex.quote(script) + ' ' + shlex.join(sorted(tokens)))


def load_endpoints(parser, extra_ips=()):
    conf = parser.get()
    hosts = HostConfParser(conf.config.hosts)
    hosts.load_conf_file()
    connections = ConnectionConfParser(conf.config.connections)
    connections.load_conf_file()
    helpers = generate_ip_helper_map(set(connections.hosts) | set(extra_ips), hosts.hosts, conf.applications.remote_rdma.user)
    from framework.rdma.nic_batch import discover
    discover(hosts, helpers)
    Path(conf.config.hosts + '.discovered.json').write_text(json.dumps(hosts.hosts, indent=2))
    return hosts, connections.connections, helpers


def render_command(parser, helper, role, port, peer, section='test', trace=None):
    conf = parser.get().applications.remote_rdma.get(section)
    template = conf.cmd.get(role).split('>')[0].strip()
    config = parser.get_remote_rdma_cmd_config(template, conf.cmd.config)
    config.update(binary_dir=next(item.path for item in parser.get().artifact.binary_paths if item.ip == helper.ip),
                  mlx_device_name=helper.mlx_device_name, gid=helper.gid,
                  receiver_ip=peer, port=port, trace=trace)
    # Paths in runtime configuration are absolute and contain no shell metacharacters.
    return Environment(undefined=StrictUndefined).from_string(template).render(config)


def execute_connections(parser, connections, helpers, section='test', duration=None):
    conf = parser.get().applications.remote_rdma.get(section)
    output = Path(conf.local_log)
    output.mkdir(parents=True, exist_ok=True)
    active, errors, starts = [], [], []
    transport_failed = False
    cleanup_errors = []
    primary_error = None

    def record_error(exc):
        nonlocal transport_failed
        errors.append(str(exc) or type(exc).__name__)
        transport_failed |= isinstance(exc, SSHConnectionError)

    progress(f'RUN Traffic: starting {len(connections)} receivers ({section})')
    try:
        receiver_batches = {}
        for index, connection in enumerate(connections):
            src, dst = connection['sender'], connection['receiver']
            port = conf.cmd.base_port + index + 1
            helper = helpers[dst]
            if helper.target not in receiver_batches:
                receiver_batches[helper.target] = dict(helper=helper, jobs=[], names=[], ports=[],
                                                       log_dir=helper.absolute(conf.remote_log))
            batch = receiver_batches[helper.target]
            name = f'{src}-{dst}.receiver.log'
            remote = batch['log_dir'].rstrip('/') + '/' + name
            cmd = render_command(parser, helper, 'receiver', port, src, section)
            # The one-way WRITE receiver exits without writing a trace CSV.
            # Its stdout/stderr log is still required for diagnostics.
            batch['jobs'].append((cmd, remote))
            batch['names'].append(name)
            batch['ports'].append(port)
        # Check all ports before launching any receiver; keep normal SSH pacing
        # for preflight, which also warms each host's connection.
        for batch in receiver_batches.values():
            batch['helper'].check_ports_free(batch['ports'])
        progress(f'Traffic: starting {len(connections)} receivers through '
                 f'{len(receiver_batches)} concurrent host SSH sessions')
        with ssh_spacing(0), ThreadPoolExecutor(max_workers=max(1, len(receiver_batches))) as pool:
            futures = [(batch, pool.submit(batch['helper'].start_many, batch['jobs']))
                       for batch in receiver_batches.values()]
            for batch, future in futures:
                try:
                    batch['processes'] = future.result()
                    active.extend((batch['helper'], proc, name, 'receiver')
                                  for proc, name in zip(batch['processes'], batch['names']))
                except Exception as exc:
                    record_error(exc)
        if errors:
            raise RuntimeError('; '.join(errors))
        progress('Traffic: all receivers launched; checking readiness by host')
        for batch in receiver_batches.values():
            batch['helper'].wait_ready_many(zip(batch['processes'], batch['ports']))
        progress('Traffic: all receivers ready; preparing sender batches and SSH connections')
        batches = {}
        for index, connection in enumerate(connections):
            src, dst = connection['sender'], connection['receiver']
            helper = helpers[src]
            if helper.target not in batches:
                batches[helper.target] = dict(helper=helper, jobs=[], names=[],
                    log_dir=helper.absolute(conf.remote_log),
                    trace_dir=helper.absolute(conf.remote_trace_dir) if conf.get('remote_trace_dir') else None)
            batch = batches[helper.target]
            name = f'{src}-{dst}.sender.log'
            remote = batch['log_dir'].rstrip('/') + '/' + name
            trace = batch['trace_dir'].rstrip('/') + f'/{src}-{dst}.trace' if batch['trace_dir'] else None
            cmd = render_command(parser, helper, 'sender', conf.cmd.base_port + index + 1, dst, section, trace)
            if 'ib_write_trace' in cmd:
                cmd += ' --trace_log ' + shlex.quote(remote + '.csv')
            batch['jobs'].append((cmd, remote))
            batch['names'].append(name)
        # Receivers may take minutes to start, outliving ControlPersist. Warm the
        # sender connections immediately before the concurrent launch, with the
        # normal SSH spacing still enabled and before any sender is started.
        for batch in batches.values():
            batch['helper'].ssh('true')
        progress(f'Traffic: starting {len(connections)} senders through {len(batches)} concurrent host SSH sessions')
        with ssh_spacing(0), ThreadPoolExecutor(max_workers=max(1, len(batches))) as pool:
            def sender_batch(batch):
                helper = batch['helper']
                processes = helper.start_many(batch['jobs'])
                return [(helper, proc, name, 'sender')
                        for proc, name in zip(processes, batch['names'])]
            futures = [pool.submit(sender_batch, batch) for batch in batches.values()]
            # Consume all host futures; failed batches retain every launch intent
            # in helper.processes and the journal for the existing cleanup path.
            for future in futures:
                try:
                    for item in future.result():
                        active.append(item)
                        starts.append({'connection': item[2], 'started': item[1]['started']})
                except Exception as exc:
                    record_error(exc)
        if errors:
            raise RuntimeError('; '.join(errors))
        Path(output / 'starts.json').write_text(json.dumps(starts, indent=2))
        deadline = time.monotonic() + (duration if duration is not None else conf.cmd.timeout)
        progress(f'Traffic: all senders started; waiting for completion '
                 f'({"duration" if duration is not None else "timeout"} '
                 f'{duration if duration is not None else conf.cmd.timeout}s)')
        process_groups = {}
        for helper, proc, _, _ in active:
            process_groups.setdefault(helper.target, (helper, []))[1].append(proc)
        completed = {}
        while True:
            monitor_dir = os.environ.get('ARTIFACT_SWITCH_LOG')
            if monitor_dir:
                switches = yaml.safe_load(Path(parser.get().config.switches).read_text())['switches']
                for switch in switches:
                    exit_file = Path(monitor_dir) / (switch + '.ssh-exit')
                    if exit_file.exists():
                        raise SSHConnectionError(f'{switch}: switchd SSH console exited with {exit_file.read_text().strip()}')
            for helper, processes in process_groups.values():
                pending = [proc for proc in processes if proc['token'] not in completed]
                if not pending:
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if duration is None:
                        raise TimeoutError('Trace did not complete before measurement timeout')
                    break
                statuses = helper.exit_codes_many(pending, timeout=min(60, remaining))
                for proc, code in zip(pending, statuses):
                    if code is not None:
                        completed[proc['token']] = code
                        if code != 0:
                            raise RuntimeError(f'Process exited {code}: {proc["log"]}')
            codes = [completed.get(p['token']) for _, p, _, role in active if role == 'sender']
            receiver_codes = [completed.get(p['token']) for _, p, _, role in active if role == 'receiver']
            if any(code not in (None, 0) for code in codes):
                raise RuntimeError(f'Sender process failed: {codes}')
            if duration is not None:
                # Infinite BW jobs must survive the complete requested window.
                if any(code is not None for code in codes + receiver_codes):
                    raise RuntimeError('Continuous bandwidth process exited early')
                if time.monotonic() >= deadline:
                    break
            elif all(code == 0 for code in codes + receiver_codes):
                break
            elif time.monotonic() >= deadline:
                raise TimeoutError('Trace did not complete before measurement timeout')
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        progress('DONE Traffic: measurement finished')
    except BaseException as exc:
        progress(f'FAIL Traffic: {exc or type(exc).__name__}')
        record_error(exc)
        primary_error = exc
    finally:
        progress('RUN Collection: stopping owned processes, collecting logs and counters')
        # Include launch intents whose SSH call failed before returning a handle.
        cleanup_groups = {}
        for helper in helpers.values():
            for proc in helper.processes:
                cleanup_groups.setdefault(helper.target, (helper, {}))[1][proc['token']] = proc
        for helper, proc, _, _ in active:
            cleanup_groups.setdefault(helper.target, (helper, {}))[1][proc['token']] = proc
        expected_stop = duration is not None and not errors
        for helper, owned in cleanup_groups.values():
            processes = list(owned.values())
            try:
                for proc, code in zip(processes, helper.exit_codes_many(processes)):
                    proc['exit_code'] = code
                    proc['expected_stop'] = expected_stop
            except Exception as exc:
                record_error(exc)
            # Always attempt cleanup, even when the final status read failed.
            try:
                helper.stop_many(processes)
                for proc in processes:
                    proc['stopped'] = time.time()
            except Exception as exc:
                record_error(exc)
                cleanup_errors.append(str(exc))
        try:
            verify_traffic_stopped(helpers)
        except Exception as exc:
            record_error(exc)
            cleanup_errors.append(str(exc))
        # Capture the measurement boundary before any large log transfers.
        collect_counters(helpers, output, '.counters.after', on_error=record_error)
        for helper, owned in cleanup_groups.values():
            directories = sorted({str(Path(proc['log']).parent) for proc in owned.values()})
            for directory in directories:
                try:
                    helper.sync_remote_directory_to_local(directory, output)
                except Exception as exc:
                    record_error(exc)
        for _, proc, name, role in active:
            required = [name]
            if role == 'sender' and 'ib_write_trace' in proc['command']:
                required.append(name + '.csv')
            for filename in required:
                if not (output / filename).is_file():
                    record_error(FileNotFoundError(f'Missing required collected file: {filename}'))
        (output / 'execution.json').write_text(json.dumps({'processes': [p for _, owned in cleanup_groups.values() for p in owned.values()], 'errors': errors,
            'cleanup_confirmed': not cleanup_errors, 'cleanup_errors': cleanup_errors,
            'transport_failed': transport_failed}, indent=2))
        if primary_error is not None and not isinstance(primary_error, Exception):
            raise primary_error
        if errors:
            progress('FAIL Traffic/collection: see execution.json for errors')
            raise TrafficExecutionError('; '.join(errors),
                                        can_continue=not cleanup_errors and not transport_failed) from primary_error
        progress(f'DONE Collection: {output}')
    return active


@click.command()
def concurrent_start(test_conf_parser):
    _, connections, helpers = load_endpoints(test_conf_parser)
    conf = test_conf_parser.get().applications.remote_rdma.test
    duration = conf.cmd.timeout if '--run_infinitely' in conf.cmd.sender else None
    execute_connections(test_conf_parser, connections, helpers, duration=duration)


@click.command()
def sequential_start(test_conf_parser):
    _, connections, helpers = load_endpoints(test_conf_parser)
    conf = test_conf_parser.get().applications.remote_rdma.test
    duration = conf.cmd.timeout if '--run_infinitely' in conf.cmd.sender else None
    for connection in connections:
        execute_connections(test_conf_parser, [connection], helpers, duration=duration)
