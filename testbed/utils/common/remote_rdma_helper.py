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
               '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=3',
               '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3', '-o', 'ForwardAgent=no']
if os.environ.get('ARTIFACT_SSH_CONFIG'):
    SSH_OPTIONS += ['-F', os.environ['ARTIFACT_SSH_CONFIG']]
if os.environ.get('ARTIFACT_KNOWN_HOSTS'):
    SSH_OPTIONS += ['-o', 'UserKnownHostsFile=' + os.environ['ARTIFACT_KNOWN_HOSTS']]

_ssh_interval = 0
_ssh_finished = None


@contextlib.contextmanager
def ssh_spacing(seconds):
    """Space sequential SSH requests across all hosts within one check run."""
    global _ssh_interval, _ssh_finished
    previous = _ssh_interval, _ssh_finished
    _ssh_interval, _ssh_finished = seconds, None
    try:
        yield
    finally:
        _ssh_interval, _ssh_finished = previous


def logged_run(argv, timeout=60, check=True):
    global _ssh_finished
    spaced = _ssh_interval > 0 and argv[0] == 'ssh' and '-G' not in argv
    if spaced and _ssh_finished is not None:
        remaining = _ssh_interval - (time.monotonic() - _ssh_finished)
        if remaining > 0:
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
                                    'exit_code': result.returncode, 'timeout': error is not None,
                                    'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
    if error:
        raise error
    if check and result.returncode:
        raise RuntimeError(f'{shlex.join(argv)} exited {result.returncode}: {result.stderr or result.stdout}')
    return result


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
        wanted = __import__('ipaddress').IPv6Address('::ffff:' + self.ip)
        for line in self.ssh(cmd).stdout.splitlines():
            fields = line.split(maxsplit=2)
            if len(fields) == 3 and __import__('ipaddress').IPv6Address(fields[1]) == wanted and fields[2] == 'RoCE v2':
                self.gid = int(fields[0])
                break
        if self.gid is None:
            raise RuntimeError(f'{self.ip}: no matching RoCE v2 GID')
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
        q = shlex.quote
        log_path = self.absolute(log_path)
        token = uuid.uuid4().hex
        state = log_path + '.' + token
        # The token in the process environment and /proc start time prevent PID reuse kills.
        script = (f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {q(state + ".pid")}; '
                  f'{command}; rc=$?; echo "$rc" > {q(state + ".exit")}; exit "$rc"')
        proc = {'state': state, 'token': token, 'log': log_path, 'target': self.target,
                'started': time.time(), 'command': command}
        self.processes.append(proc)
        journal = os.environ.get('ARTIFACT_PROCESS_JOURNAL')
        if journal:
            with open(journal, 'a') as out:
                out.write(json.dumps(proc) + '\n')
        self.ssh(f'mkdir -p {q(str(Path(log_path).parent))}; '
                 f'ARTIFACT_PROCESS_TOKEN={token} nohup setsid bash -c {q(script)} '
                 f'> {q(log_path)} 2>&1 < /dev/null &')
        self.ssh(f'for i in $(seq 1 50); do test -s {q(state + ".pid")} && exit 0; sleep .1; done; exit 1')
        return proc

    def exit_code(self, proc):
        result = self.ssh('if test -f {0}; then cat {0}; else echo running; fi'.format(shlex.quote(proc['state'] + '.exit'))).stdout.strip()
        return None if result == 'running' else int(result)

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
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.exit_code(proc) is not None:
                raise RuntimeError(f'Receiver exited before ready: {proc["log"]}')
            if self.ssh(f'ss -H -ltn "sport = :{int(port)}"').stdout.strip():
                return
            time.sleep(0.25)
        raise TimeoutError(f'{self.target}: port {port} not ready')

    def stop(self, proc):
        q = shlex.quote
        signal = 'sudo -n kill' if proc.get('sudo') else 'kill'
        # Refuse to signal any process whose identity no longer matches the journal.
        cmd = f'''test -f {q(proc['state'] + '.pid')} || exit 0
read pid stamp < {q(proc['state'] + '.pid')}
test -r /proc/$pid/stat || exit 0
test "$(awk '{{print $22}}' /proc/$pid/stat)" = "$stamp" || exit 0
tr '\\0' '\\n' < /proc/$pid/environ | grep -Fx {q('ARTIFACT_PROCESS_TOKEN=' + proc['token'])} >/dev/null || exit 1
{signal} -TERM -- -$pid
for i in $(seq 1 50); do {signal} -0 -- -$pid 2>/dev/null || exit 0; sleep .1; done
{signal} -KILL -- -$pid
for i in $(seq 1 50); do {signal} -0 -- -$pid 2>/dev/null || exit 0; sleep .1; done
exit 1'''
        self.ssh(cmd, timeout=20)

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

    def get_counter(self):
        return self.ssh(f'ethtool -S {shlex.quote(self.interface)}; '
                        f'for f in /sys/class/infiniband/{self.mlx_device_name}/ports/1/counters/*; '
                        'do printf "%s " "${f##*/}"; cat "$f"; done').stdout


def generate_ip_helper_map(ip_list, info, remote_user):
    return {ip: RemoteRDMAHelper(info[ip].get('user', remote_user), info[ip]['hostname'], info[ip]['eth'], ip) for ip in sorted(ip_list)}


def sync_log_local(remote_path, target_path):
    __import__('shutil').copy2(remote_path, target_path)
