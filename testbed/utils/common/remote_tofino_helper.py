"""Checked switch deployment with a persistent local tmux SSH console."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from jinja2 import Environment, StrictUndefined
from common.remote_rdma_helper import RemoteRDMAHelper, SSH_OPTIONS, logged_run

from common.nix_environment import NIX_ENV
from common.progress import progress


# Only the named daemon on the selected switch is replaced. Failed SSH or
# signal delivery must abort deployment rather than start a second daemon.
STOP_SWITCHD = '''pids=$(pgrep -x bf_switchd) || { rc=$?; test "$rc" -eq 1 && exit 0; exit "$rc"; }
echo "Stopping existing bf_switchd PIDs: $pids"
signal_switchd() {
    for pid in $pids; do
        test "$(cat /proc/$pid/comm 2>/dev/null || true)" = bf_switchd || continue
        sudo -n kill -"$1" -- "$pid" || {
            test "$(cat /proc/$pid/comm 2>/dev/null || true)" != bf_switchd || return 1
        }
    done
}
switchd_gone() {
    pgrep -x bf_switchd >/dev/null && return 1
    rc=$?
    test "$rc" -eq 1 && return 0
    exit "$rc"
}
signal_switchd TERM
for i in $(seq 1 50); do switchd_gone && exit 0; sleep .1; done
signal_switchd KILL
for i in $(seq 1 50); do switchd_gone && exit 0; sleep .1; done
echo "bf_switchd is still running; refusing to start another daemon" >&2
exit 1'''


class RemoteTofinoHelper:
    def __init__(self, remote_user, switch_hostname, remote_cwd, arch, switch_id=None):
        self.remote = RemoteRDMAHelper(remote_user, switch_hostname)
        self.remote_cwd = self.remote.absolute(remote_cwd)
        self.arch = arch
        self.switch_id = switch_id or switch_hostname
        self.run_id = os.environ.get('ARTIFACT_RUN_ID', 'manual')
        self.log_dir = Path(os.environ.get('ARTIFACT_SWITCH_LOG', 'logs/switchd'))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session = 'artifact-' + self.run_id + '-' + self.switch_id
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.session):
            raise ValueError('Invalid run-id/switch id for tmux')

    def render(self, command, **config):
        return Environment(undefined=StrictUndefined).from_string(command).render(config)

    def sync_repo(self, repo_path, exclude_paths):
        self.remote.ssh('mkdir -p ' + shlex.quote(self.remote_cwd))
        # Keep the original data/log/trace exclusions mandatory, even if a
        # caller omits them. Artifact snapshots also contain measurement data.
        excludes = set(exclude_paths) | {'.git', '.env', 'logs', 'data', 'trace', 'artifact',
                                        'third_party', '*venv*', '__pycache__', '*.pem', '*.key'}
        logged_run(['rsync', '-az', *[f'--exclude={p}' for p in sorted(excludes)],
                    '-e', shlex.join(['ssh', *SSH_OPTIONS]), str(repo_path) + '/',
                    self.remote.target + ':' + self.remote_cwd + '/'], timeout=300)

    def remote_build(self, build_cmd, p4program_path):
        self.remote.ssh(NIX_ENV + 'cd ' + shlex.quote(self.remote_cwd) + ' && ' +
                        self.render(build_cmd, p4program_path=p4program_path), timeout=1800)

    def remote_deploy(self, deploy_cmd, p4program_name):
        q = shlex.quote
        owner_path = self.log_dir / (self.switch_id + '.owner.json')
        if owner_path.exists():
            owner = json.loads(owner_path.read_text())
            if owner['target'] != self.remote.target or owner['run_id'] != self.run_id:
                raise RuntimeError('Existing switch console ownership mismatch')
            self.remote.stop(owner['process'])
            logged_run(['tmux', 'kill-session', '-t', self.session], check=False)
        progress(f'Replacing existing switchd: {self.switch_id}')
        self.remote.ssh(STOP_SWITCHD, timeout=30)
        state = self.remote_cwd + '/artifact-process-' + self.run_id + '-' + self.switch_id
        token = __import__('uuid').uuid4().hex
        command = self.render(deploy_cmd, p4program_name=p4program_name)
        remote_script = (f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {q(state + ".pid")}; '
                         + NIX_ENV + 'cd ' + q(self.remote_cwd) + ' && ' + command +
                         f'; rc=$?; echo "$rc" > {q(state + ".exit")}; exit "$rc"')
        ssh_argv = ['ssh', *SSH_OPTIONS, '-tt', self.remote.target,
                    f'ARTIFACT_PROCESS_TOKEN={token} setsid -w bash -c {q(remote_script)}']
        exit_file = self.log_dir / (self.switch_id + '.ssh-exit')
        exit_file.unlink(missing_ok=True)
        launcher = self.log_dir / (self.switch_id + '.console.sh')
        launcher.write_text('#!/bin/bash\n' + shlex.join(ssh_argv) + '\nrc=$?\nprintf "%s\\n" "$rc" > ' + q(str(exit_file)) + '\nexit "$rc"\n')
        proc = dict(state=state, token=token, sudo=True, target=self.remote.target, log=str(self.log_dir / (self.switch_id + '.log')))
        owner_path.write_text(json.dumps(dict(run_id=self.run_id, target=self.remote.target, process=proc, session=self.session)))
        # Create an idle session, attach pipe-pane, then execute one quoted script path.
        logged_run(['tmux', 'new-session', '-d', '-s', self.session])
        logged_run(['tmux', 'set-option', '-t', self.session, 'remain-on-exit', 'on'])
        logged_run(['tmux', 'pipe-pane', '-t', self.session, '-o', 'cat >> ' + q(proc['log'])])
        logged_run(['tmux', 'send-keys', '-t', self.session, '-l', 'exec bash ' + q(str(launcher))])
        logged_run(['tmux', 'send-keys', '-t', self.session, 'Enter'])
        # A tmux session alone is not evidence that switchd is healthy.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if exit_file.exists():
                raise RuntimeError('switchd SSH exited: ' + exit_file.read_text())
            if self.remote.ssh('pgrep -x bf_switchd', check=False).returncode == 0:
                return
            time.sleep(1)
        raise TimeoutError('switchd did not start')

    def remote_config(self, config_cmd, cp_script_path, port, topo, switches, hosts):
        self.remote.ssh('cd ' + shlex.quote(self.remote_cwd) +
                        f' && bash scripts/remote_tofino/wait_port.sh --port={int(port)}', timeout=180)
        cmd = self.render(config_cmd, cp_script_path=cp_script_path, hostname=self.switch_id,
                          topo=topo, switches=switches, hosts=hosts, port=int(port))
        self.remote.ssh(NIX_ENV + 'cd ' + shlex.quote(self.remote_cwd) + ' && ' + cmd, timeout=300)
