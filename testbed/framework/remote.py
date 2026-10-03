"""Non-interactive SSH and task-owned remote process management."""
import hashlib
import contextlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

from jinja2 import Environment, StrictUndefined

SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
               '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3', '-o', 'ForwardAgent=no']
if os.environ.get('ARTIFACT_SSH_CONFIG'):
    SSH_OPTIONS += ['-F', os.environ['ARTIFACT_SSH_CONFIG']]
if os.environ.get('ARTIFACT_KNOWN_HOSTS'):
    SSH_OPTIONS += ['-o', 'UserKnownHostsFile=' + os.environ['ARTIFACT_KNOWN_HOSTS']]

_ssh_interval = 0
_ssh_finished = None


class SSHConnectionError(RuntimeError):
    """Stop probing after SSH transport failure; do not turn it into a missing dependency."""


@contextlib.contextmanager
def ssh_spacing(seconds=2):
    """Space sequential SSH/rsync requests across hosts in every hardware stage."""
    global _ssh_interval, _ssh_finished
    previous = _ssh_interval, _ssh_finished
    _ssh_interval, _ssh_finished = seconds, None
    try:
        yield
    finally:
        _ssh_interval, _ssh_finished = previous


def logged_run(argv, timeout=60, check=True):
    global _ssh_finished
    pacing_seconds = 0
    network_request = argv[0] in ('rsync', 'scp') or (argv[0] == 'ssh' and '-G' not in argv)
    spaced = _ssh_interval > 0 and network_request
    if spaced and _ssh_finished is not None:
        remaining = _ssh_interval - (time.monotonic() - _ssh_finished)
        if remaining > 0:
            pacing_seconds = remaining
            time.sleep(remaining)
    started = time.time()
    error = None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        result = subprocess.CompletedProcess(argv, 124, decode(exc.stdout), decode(exc.stderr))
        error = exc
    finally:
        if spaced:
            _ssh_finished = time.monotonic()
    log = os.environ.get('ARTIFACT_COMMAND_LOG')
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with open(log, 'a') as stream:
            stream.write(json.dumps({'started': started, 'finished': time.time(), 'argv': argv,
                                    'pacing_seconds': pacing_seconds,
                                    'exit_code': result.returncode, 'timeout': error is not None,
                                    'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
    if error:
        if network_request:
            raise SSHConnectionError(f'SSH request timed out; stopping remote checks: {shlex.join(argv)}') from error
        raise error
    if network_request and result.returncode == 255:
        raise SSHConnectionError(f'SSH connection failed; stopping remote checks: {result.stderr or result.stdout}')
    if check and result.returncode:
        raise RuntimeError(f'{shlex.join(argv)} exited {result.returncode}: {result.stderr or result.stdout}')
    return result


def find_roce_v2_gid(output, ip):
    """Use the original discovery rules for both single-port and batch output."""
    wanted = __import__('ipaddress').IPv6Address('::ffff:' + ip)
    for line in output.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) == 3 and __import__('ipaddress').IPv6Address(fields[1]) == wanted and fields[2] == 'RoCE v2':
            return int(fields[0])
    raise RuntimeError(f'{ip}: no matching RoCE v2 GID')


class RemoteRDMAHelper:
    def __init__(self, remote_user, hostname, interface='', ip=''):
        if not remote_user or not hostname or hostname.startswith('-'):
            raise ValueError('Explicit remote user and management address required')
        self.remote_user, self.hostname = remote_user, hostname
        self.interface, self.ip = interface, ip
        self.mlx_device_name = self.bus_info = self.gid = None
        self.processes = []

    @property
    def target(self):
        return f'{self.remote_user}@{self.hostname}'

    def ssh(self, command, timeout=60, check=True):
        # Load the login environment, then replace that shell before executing
        # the command. Otherwise explicit exit can run ~/.bash_logout, whose
        # clear_console failure under errexit masks a successful PID check.
        script = 'exec bash -c ' + shlex.quote('set -euo pipefail; ' + command)
        return logged_run(['ssh', *SSH_OPTIONS, self.target,
                           'bash -lc ' + shlex.quote(script)], timeout, check)

    def absolute(self, path):
        if path.startswith('~/'):
            path = path[2:]
        if path.startswith('/'):
            return path
        home = self.ssh('printf "%s" "$HOME"').stdout
        return home.rstrip('/') + '/' + path

    def get_mellanox_info(self, host_conf_parser, require_gid=True):
        """Always probe; update only the in-memory/runtime snapshot."""
        q = shlex.quote
        # Probe sysfs directly: ibdev2netdev is not shipped by every inbox stack.
        command = 'for dev in /sys/class/infiniband/mlx*; do for net in "$dev"/device/net/*; do printf "%s %s\\n" "${dev##*/}" "${net##*/}"; done; done'
        matches = [line.split() for line in self.ssh(command).stdout.splitlines()]
        self.mlx_device_name = next((dev for dev, iface in matches if iface == self.interface), None)
        if not self.mlx_device_name:
            raise RuntimeError(f'{self.target}: no verbs mapping for {self.interface}')
        self.bus_info = self.ssh(f'ethtool -i {q(self.interface)}').stdout
        self.bus_info = re.search(r'bus-info:\s*(\S+)', self.bus_info).group(1)
        old = host_conf_parser.hosts[self.ip]
        for key in ('mlx_device_name', 'bus_info'):
            if old.get(key) and old[key] != getattr(self, key):
                raise RuntimeError(f'{self.ip}: configured {key} differs from device probe')
        if not require_gid:
            host_conf_parser.add_host_info(self.ip, {k: getattr(self, k) for k in ('mlx_device_name', 'bus_info')})
            return {'mlx_device_name': self.mlx_device_name, 'bus_info': self.bus_info}
        prefix = f'/sys/class/infiniband/{self.mlx_device_name}/ports/1'
        cmd = f'for f in {prefix}/gids/*; do printf "%s %s %s\\n" "${{f##*/}}" "$(cat "$f")" "$(cat {prefix}/gid_attrs/types/${{f##*/}})"; done'
        self.gid = find_roce_v2_gid(self.ssh(cmd).stdout, self.ip)
        host_conf_parser.add_host_info(self.ip, {k: getattr(self, k) for k in ('mlx_device_name', 'bus_info', 'gid')})

    def config_mlxreg(self, reg_name, option_table):
        q = shlex.quote
        opts = ','.join(f'{key}={int(value)}' for key, value in option_table.items())
        base = f'sudo -n mlxreg -d {q(self.bus_info)} --reg_name {q(reg_name)}'
        self.ssh(base + ' -y --set ' + q(opts))
        output = self.ssh(base + ' --get').stdout
        for key, value in option_table.items():
            match = re.search(r'\b' + re.escape(key) + r'\s*\|?\s*(0x[0-9a-fA-F]+|\d+)\b', output)
            if not match or int(match[1], 16 if match[1].startswith('0x') else 10) != int(value):
                raise RuntimeError(f'{self.ip}: {reg_name}.{key} readback failed')

    def start(self, command, log_path):
        return self.start_many([(command, log_path)])[0]

    def start_many(self, commands):
        """Launch independent processes through one SSH session on this host."""
        q = shlex.quote
        processes, launches = [], []
        for command, log_path in commands:
            log_path = self.absolute(log_path)
            token = uuid.uuid4().hex
            state = log_path + '.' + token
            # Preserve per-flow ownership, exit status and recovery metadata.
            script = (f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {q(state + ".pid")}; '
                      f'{command}; rc=$?; echo "$rc" > {q(state + ".exit")}; exit "$rc"')
            proc = {'state': state, 'token': token, 'log': log_path, 'target': self.target,
                    'started': time.time(), 'command': command}
            processes.append(proc)
            launches.append(f'ARTIFACT_PROCESS_TOKEN={token} nohup setsid bash -c {q(script)} '
                            f'> {q(log_path)} 2>&1 < /dev/null &')
        if not processes:
            return []
        self.processes.extend(processes)
        journal = os.environ.get('ARTIFACT_PROCESS_JOURNAL')
        if journal:
            with open(journal, 'a') as out:
                out.write(''.join(json.dumps(proc) + '\n' for proc in processes))
        directories = sorted({str(Path(proc['log']).parent) for proc in processes})
        pid_files = shlex.join([proc['state'] + '.pid' for proc in processes])
        # Start every process before waiting for any PID file. No per-flow SSH
        # requests or controller-side sleeps are inserted into the launch burst.
        wait = (f'for i in $(seq 1 50); do ready=1; for file in {pid_files}; do '
                'if ! test -s "$file"; then ready=0; fi; done; '
                'if test "$ready" = 1; then exit 0; fi; sleep .1; done; exit 1')
        self.ssh('mkdir -p ' + shlex.join(directories) + '\n' +
                 '\n'.join(launches) + '\n' + wait)
        return processes

    def exit_code(self, proc):
        result = self.ssh('if test -f {0}; then cat {0}; else echo running; fi'.format(shlex.quote(proc['state'] + '.exit'))).stdout.strip()
        return None if result == 'running' else int(result)

    def exit_codes_many(self, processes, timeout=60):
        """Read one ordered snapshot without one SSH request per process."""
        processes = list(processes)
        if not processes:
            return []
        commands = []
        for index, proc in enumerate(processes):
            path = shlex.quote(proc['state'] + '.exit')
            commands.append(f'printf "{index} "; if test -f {path}; then cat {path}; '
                            'else echo running; fi')
        lines = self.ssh('\n'.join(commands), timeout=timeout).stdout.splitlines()
        codes = []
        for index, line in enumerate(lines):
            fields = line.split()
            if len(fields) != 2 or fields[0] != str(index) or not re.fullmatch(r'running|[0-9]+', fields[1]):
                raise RuntimeError(f'{self.target}: invalid process status: {line}')
            codes.append(None if fields[1] == 'running' else int(fields[1]))
        if len(codes) != len(processes):
            raise RuntimeError(f'{self.target}: incomplete process status snapshot')
        return codes

    def wait(self, proc, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code = self.exit_code(proc)
            if code is not None:
                if code:
                    raise RuntimeError(f'{self.target}: process exited {code}: {proc["log"]}')
                return code
            time.sleep(0.25)
        raise TimeoutError(f'{self.target}: process timed out: {proc["log"]}')

    def wait_ready(self, proc, port, timeout=30):
        self.wait_ready_many([(proc, port)], timeout)

    def check_ports_free(self, ports):
        """Apply the existing listening-port check in one SSH session."""
        ports = list(ports)
        if not ports:
            return
        commands = []
        for port in ports:
            port = int(port)
            commands.append(f'listening=$(ss -H -ltn "sport = :{port}"); '
                            f'if test -n "$listening"; then echo {port}; fi')
        occupied = self.ssh('\n'.join(commands)).stdout.split()
        if occupied:
            raise RuntimeError(f'{self.target}: port {occupied[0]} already occupied')

    def wait_ready_many(self, receivers, timeout=30):
        """Check exit files and listening ports for the whole host per SSH poll."""
        receivers = list(receivers)
        if not receivers:
            return
        commands = []
        for index, (proc, port) in enumerate(receivers):
            commands.append(
                f'if test -f {shlex.quote(proc["state"] + ".exit")}; then '
                f'echo "{index} exited"; else '
                f'listening=$(ss -H -ltn "sport = :{int(port)}"); '
                f'if test -n "$listening"; then echo "{index} ready"; '
                f'else echo "{index} pending"; fi; fi')
        deadline = time.monotonic() + timeout
        pending = list(range(len(receivers)))
        while time.monotonic() < deadline:
            pending = []
            lines = self.ssh('\n'.join(commands)).stdout.splitlines()
            if len(lines) != len(receivers):
                raise RuntimeError(f'{self.target}: incomplete receiver readiness snapshot')
            for expected, line in enumerate(lines):
                index, status = line.split()
                index = int(index)
                if index != expected or status not in ('exited', 'ready', 'pending'):
                    raise RuntimeError(f'{self.target}: invalid receiver readiness status: {line}')
                if status == 'exited':
                    raise RuntimeError(f'Receiver exited before ready: {receivers[index][0]["log"]}')
                if status == 'pending':
                    pending.append(index)
            if not pending:
                return
            time.sleep(0.25)
        ports = ', '.join(str(receivers[index][1]) for index in pending)
        raise TimeoutError(f'{self.target}: port(s) {ports} not ready')

    def _stop_command(self, proc):
        q = shlex.quote
        signal = 'sudo -n kill' if proc.get('sudo') else 'kill'
        pid_target = '-$pid' if proc.get('process_group', True) else '$pid'
        # Refuse to signal any process whose identity no longer matches the journal.
        cmd = f'''test -f {q(proc['state'] + '.pid')} || exit 0
read pid stamp < {q(proc['state'] + '.pid')}
test -r /proc/$pid/stat || exit 0
test "$(awk '{{print $22}}' /proc/$pid/stat)" = "$stamp" || exit 0
tr '\\0' '\\n' < /proc/$pid/environ | grep -Fx {q('ARTIFACT_PROCESS_TOKEN=' + proc['token'])} >/dev/null || exit 1
{signal} -TERM -- {pid_target}
for i in $(seq 1 50); do {signal} -0 -- {pid_target} 2>/dev/null || exit 0; sleep .1; done
{signal} -KILL -- {pid_target}
for i in $(seq 1 50); do {signal} -0 -- {pid_target} 2>/dev/null || exit 0; sleep .1; done
exit 1'''
        return cmd

    def stop(self, proc):
        self.ssh(self._stop_command(proc), timeout=20)

    def stop_many(self, processes):
        """Clean owned processes in one SSH session with overlapping grace periods.

        Each child keeps strict shell error handling and its own identity checks.
        A failed child cannot prevent cleanup of the other launch intents.
        """
        processes = list(processes)
        errors = []
        # Recovery can span many attempts. Bound the quoted SSH argument size.
        for offset in range(0, len(processes), 64):
            try:
                self._stop_many_batch(processes[offset:offset + 64])
            except SSHConnectionError:
                raise
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))

    def _stop_many_batch(self, processes):
        if not processes:
            return
        commands = []
        for index, proc in enumerate(processes):
            script = shlex.quote('set -euo pipefail; ' + self._stop_command(proc))
            commands.append(f'( rc=0; bash -c {script} >/dev/null || rc=$?; '
                            f'printf "{index} %s\\n" "$rc" ) &')
        result = self.ssh('\n'.join(commands) + '\nwait', timeout=30)
        statuses = {}
        for line in result.stdout.splitlines():
            fields = line.split()
            if (len(fields) != 2 or not all(value.isdigit() for value in fields)
                    or int(fields[0]) in statuses or int(fields[0]) >= len(processes)):
                raise RuntimeError(f'{self.target}: invalid cleanup status: {line}')
            statuses[int(fields[0])] = int(fields[1])
        failures = [f'{proc["state"]}: exit {statuses.get(index, "missing")}'
                    for index, proc in enumerate(processes) if statuses.get(index) != 0]
        if failures:
            raise RuntimeError(f'{self.target}: cleanup failed: ' + '; '.join(failures))

    def run_command(self, cmd, config, timeout, log_path, is_receiver=False):
        config = dict(config, mlx_device_name=self.mlx_device_name, gid=self.gid, log_path=log_path)
        rendered = Environment(undefined=StrictUndefined).from_string(cmd).render(config)
        proc = self.start(rendered, log_path)
        if not is_receiver:
            try:
                self.wait(proc, timeout)
            finally:
                self.stop(proc)
        return proc

    def stop_command(self, kill_cmd=None):
        for proc in self.processes:
            self.stop(proc)

    def sync_local_to_remote(self, local_path, remote_path):
        remote_path = self.absolute(remote_path)
        self.ssh('mkdir -p ' + shlex.quote(remote_path))
        logged_run(['rsync', '-az', '--exclude=.git', '-e', shlex.join(['ssh', *SSH_OPTIONS]),
                    str(local_path).rstrip('/') + '/', self.target + ':' + shlex.quote(remote_path) + '/'], 300)

    def sync_remote_to_local(self, remote_path, local_path):
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        logged_run(['scp', *SSH_OPTIONS, self.target + ':' + remote_path, str(local_path)], 300)

    def sync_remote_directory_to_local(self, remote_path, local_path):
        """Merge an attempt directory; never delete another host's collected files."""
        Path(local_path).mkdir(parents=True, exist_ok=True)
        logged_run(['rsync', '-az', '-e', shlex.join(['ssh', *SSH_OPTIONS]),
                    self.target + ':' + shlex.quote(remote_path.rstrip('/') + '/'),
                    str(local_path).rstrip('/') + '/'], 300)

    def counter_command(self):
        return (f'ethtool -S {shlex.quote(self.interface)}; '
                f'for f in /sys/class/infiniband/{self.mlx_device_name}/ports/1/counters/*; '
                'do printf "%s " "${f##*/}"; cat "$f"; done')

    def get_counter(self):
        return self.ssh(self.counter_command()).stdout


def generate_ip_helper_map(ip_list, info, remote_user):
    return {ip: RemoteRDMAHelper(info[ip].get('user', remote_user), info[ip]['hostname'], info[ip]['eth'], ip) for ip in sorted(ip_list)}


def sync_log_local(remote_path, target_path):
    __import__('shutil').copy2(remote_path, target_path)
