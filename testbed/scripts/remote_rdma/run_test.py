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
from conf_parser.yaml_parser import HostConfParser, ConnectionConfParser
from common.remote_rdma_helper import generate_ip_helper_map
from common.progress import progress


def load_endpoints(parser, extra_ips=()):
    conf = parser.get()
    hosts = HostConfParser(conf.config.hosts)
    hosts.load_conf_file()
    connections = ConnectionConfParser(conf.config.connections)
    connections.load_conf_file()
    helpers = generate_ip_helper_map(set(connections.hosts) | set(extra_ips), hosts.hosts, conf.applications.remote_rdma.user)
    for helper in helpers.values():
        helper.get_mellanox_info(hosts)
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
    progress(f'RUN Traffic: starting {len(connections)} receivers ({section})')
    try:
        for index, connection in enumerate(connections):
            src, dst = connection['sender'], connection['receiver']
            port = conf.cmd.base_port + index + 1
            helper = helpers[dst]
            if helper.ssh(f'ss -H -ltn "sport = :{port}"').stdout.strip():
                raise RuntimeError(f'{helper.target}: port {port} already occupied')
            remote = helper.absolute(f'{conf.remote_log}/{src}-{dst}.receiver.log')
            cmd = render_command(parser, helper, 'receiver', port, src, section)
            # The one-way WRITE receiver exits without writing a trace CSV.
            # Its stdout/stderr log is still required for diagnostics.
            proc = helper.start(cmd, remote)
            active.append((helper, proc, f'{src}-{dst}.receiver.log', 'receiver'))
            helper.wait_ready(proc, port)
        progress(f'Traffic: all receivers ready; starting {len(connections)} senders')
        with ThreadPoolExecutor(max_workers=max(1, len(connections))) as pool:
            def sender(index, connection):
                src, dst = connection['sender'], connection['receiver']
                helper = helpers[src]
                remote = helper.absolute(f'{conf.remote_log}/{src}-{dst}.sender.log')
                trace = helper.absolute(f'{conf.remote_trace_dir}/{src}-{dst}.trace') if conf.get('remote_trace_dir') else None
                cmd = render_command(parser, helper, 'sender', conf.cmd.base_port + index + 1, dst, section, trace)
                if 'ib_write_trace' in cmd:
                    cmd += ' --trace_log ' + shlex.quote(remote + '.csv')
                proc = helper.start(cmd, remote)
                return helper, proc, f'{src}-{dst}.sender.log', 'sender'
            futures = [pool.submit(sender, i, c) for i, c in enumerate(connections)]
            # Consume all futures even if one fails, so every launched process is cleaned up.
            for future in futures:
                try:
                    item = future.result()
                    active.append(item)
                    starts.append({'connection': item[2], 'started': item[1]['started']})
                except Exception as exc:
                    errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))
        Path(output / 'starts.json').write_text(json.dumps(starts, indent=2))
        deadline = time.monotonic() + (duration if duration is not None else conf.cmd.timeout)
        progress(f'Traffic: all senders started; waiting for completion '
                 f'({"duration" if duration is not None else "timeout"} '
                 f'{duration if duration is not None else conf.cmd.timeout}s)')
        while True:
            monitor_dir = os.environ.get('ARTIFACT_SWITCH_LOG')
            if monitor_dir:
                switches = yaml.safe_load(Path(parser.get().config.switches).read_text())['switches']
                for switch in switches:
                    exit_file = Path(monitor_dir) / (switch + '.ssh-exit')
                    if exit_file.exists():
                        raise RuntimeError(f'{switch}: switchd SSH console exited with {exit_file.read_text().strip()}')
            codes = [h.exit_code(p) for h, p, _, role in active if role == 'sender']
            receiver_codes = [h.exit_code(p) for h, p, _, role in active if role == 'receiver']
            if any(code not in (None, 0) for code in codes):
                raise RuntimeError(f'Sender process failed: {codes}')
            if duration is not None:
                # Infinite BW jobs must survive the complete requested window.
                if any(code is not None for code in codes + receiver_codes):
                    raise RuntimeError('Continuous bandwidth process exited early')
                if time.monotonic() >= deadline:
                    break
            elif all(code == 0 for code in codes):
                for h, p, _, role in active:
                    if role == 'receiver':
                        h.wait(p, max(1, deadline - time.monotonic()))
                break
            elif time.monotonic() >= deadline:
                raise TimeoutError('Trace did not complete before measurement timeout')
            time.sleep(0.25)
        progress('DONE Traffic: measurement finished')
    except BaseException as exc:
        progress(f'FAIL Traffic: {exc or type(exc).__name__}')
        errors.append(str(exc))
        raise
    finally:
        progress('RUN Collection: stopping owned processes, collecting logs and counters')
        # Include launch intents whose SSH call failed before returning a handle.
        known = {p['token'] for _, p, _, _ in active}
        for helper in helpers.values():
            for proc in helper.processes:
                if proc['token'] not in known:
                    try:
                        helper.stop(proc)
                    except Exception as exc:
                        errors.append(str(exc))
        for helper, proc, name, role in active:
            try:
                proc['exit_code'] = helper.exit_code(proc)
                proc['expected_stop'] = duration is not None and not errors
                helper.stop(proc)
                proc['stopped'] = time.time()
            except Exception as exc:
                errors.append(str(exc))
            try:
                helper.sync_remote_to_local(proc['log'], output / name)
                if role == 'sender' and 'ib_write_trace' in proc['command']:
                    helper.sync_remote_to_local(proc['log'] + '.csv', output / (name + '.csv'))
            except Exception as exc:
                errors.append(str(exc))
        for ip, helper in helpers.items():
            try:
                (output / f'{ip}.counters.after').write_text(helper.get_counter())
            except Exception as exc:
                errors.append(str(exc))
        (output / 'execution.json').write_text(json.dumps({'processes': [p for _, p, _, _ in active], 'errors': errors}, indent=2))
        if errors:
            progress('FAIL Traffic/collection: see execution.json for errors')
            raise RuntimeError('; '.join(errors))
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
