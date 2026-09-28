"""Checks and narrowly scoped Debian/Ubuntu dependency preparation.

check() is read-only on devices. Nix is never installed by this module.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import stat
import subprocess
import time

from framework.remote import RemoteRDMAHelper, logged_run
from framework.nix_environment import NIX_ENV, NIX_PING, NIX_START

ROOT = Path(__file__).resolve().parents[1]


def source_digest(path):
    digest = hashlib.sha256()
    for file in sorted(Path(path).rglob('*')):
        if file.is_file() and not {'.git', '.github'} & set(file.relative_to(path).parts):
            digest.update(str(file.relative_to(path)).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def check_agent(expected):
    path = os.environ.get('SSH_AUTH_SOCK', '')
    if not path or not Path(path).exists() or not stat.S_ISSOCK(os.stat(path).st_mode):
        raise RuntimeError('SSH_AUTH_SOCK must reference an accessible dedicated SSH agent socket')
    output = logged_run(['ssh-add', '-l']).stdout
    fingerprints = [line.split()[1] for line in output.splitlines() if len(line.split()) > 1]
    if not expected:
        raise RuntimeError('Configure ssh.expected_fingerprints before accessing hardware')
    if not set(expected).issubset(fingerprints):
        raise RuntimeError('Expected SSH public-key identity is not loaded')
    return fingerprints


class CheckFailed(RuntimeError):
    """All independent checks finished, but the environment is not ready."""


def check_summary(checks):
    counts = {status: sum(c.get('status') == status for c in checks)
              for status in ('passed', 'failed', 'skipped')}
    return dict(total=len(checks), **counts)


class Environment:
    def __init__(self, deployment, report_path):
        self.config = deployment
        self.path = Path(report_path)
        self.report = {'checks': [], 'perftest': {}, 'fingerprints': []}

    def record(self, target, item, action):
        number = len(self.report['checks']) + 1
        started = time.monotonic()
        print(f'[{number}] RUN {target} {item}', flush=True)
        self.report['current'] = {'target': target, 'item': item, 'status': 'running'}
        self.save()
        try:
            detail = action()
            self.report['checks'].append(dict(target=target, item=item, passed=True, status='passed', detail=detail))
            print(f'[{number}] PASS {target} {item} ({time.monotonic() - started:.1f}s)', flush=True)
            return detail
        except Exception as exc:
            self.report['checks'].append(dict(target=target, item=item, passed=False, status='failed', error=str(exc)))
            print(f'[{number}] FAIL {target} {item} ({time.monotonic() - started:.1f}s): {exc}', flush=True)
            raise
        finally:
            self.report['current'] = None
            self.save()

    def save(self):
        self.report['summary'] = check_summary(self.report['checks'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.report, indent=2))
        tmp.replace(self.path)

    def packages(self, remote, packages, prepare):
        missing, errors = [], []
        for pkg in packages:
            result = remote.ssh('dpkg-query -W -f=\'${Status}\' ' + shlex.quote(pkg)
                                + " | grep -qx 'install ok installed'", check=False)
            if result.returncode == 255:
                errors.append(f'{pkg}: SSH failed: {result.stderr.strip()}')
            elif result.returncode:
                missing.append(pkg)
        if errors:
            raise RuntimeError('Package checks incomplete: ' + '; '.join(errors)
                               + (f'; confirmed missing: {", ".join(missing)}' if missing else ''))
        if missing:
            if not prepare:
                raise RuntimeError('Missing packages: ' + ', '.join(missing))
            remote.ssh('. /etc/os-release; test "$ID" = debian || test "$ID" = ubuntu')
            remote.ssh('sudo -n apt-get update && sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y ' + shlex.join(missing), timeout=900)
            self.packages(remote, packages, False)
        return {'installed': missing if prepare else []}

    def nix(self, remote, prepare):
        result = remote.ssh(NIX_ENV + 'command -v nix; test -d /nix/var/nix/profiles/default', check=False)
        if result.returncode:
            raise RuntimeError('Nix multi-user installation is missing/incomplete; contact the system administrator to install or repair Nix')
        result = remote.ssh(NIX_PING, check=False)
        if result.returncode == 255:
            raise RuntimeError('Nix daemon probe SSH failed: ' + result.stderr)
        if result.returncode and prepare:
            print(f'    {remote.target}: starting existing Nix daemon', flush=True)
            remote.ssh(self.config['tofino'].get('nix_daemon_start_command') or NIX_START)
            for _ in range(10):
                result = remote.ssh(NIX_PING, check=False)
                if not result.returncode or result.returncode == 255:
                    break
                time.sleep(1)
        if result.returncode:
            raise RuntimeError('Nix daemon unavailable' + (' after startup' if prepare else '; run prepare to start it')
                               + ': ' + (result.stderr or result.stdout))
        return remote.ssh(NIX_ENV + 'nix --version').stdout

    def sde(self, remote, prepare):
        sde = self.config['tofino']
        prefix = sde['sde_command']
        exists = remote.ssh(NIX_ENV + 'command -v ' + shlex.quote(prefix.split()[0]), check=False)
        if exists.returncode and prepare and sde.get('install_command'):
            remote.ssh(NIX_ENV + sde['install_command'], timeout=3600)
        inner = ('test -d "$SDE_INSTALL" && command -v p4_build.sh && command -v run_switchd.sh && '
                 'python3 -c ' + shlex.quote("import glob, os, sys; sys.path += glob.glob(os.environ['SDE_INSTALL'] + '/lib/python*/site-packages/tofino'); import bfrt_grpc.client, yaml, jinja2"))
        result = remote.ssh(NIX_ENV + prefix + ' --command ' + shlex.quote(inner), timeout=300, check=False)
        if result.returncode:
            raise RuntimeError('Configured SDE/compiler/control-plane Python unavailable; provide the matching SDE source/install_command: ' + result.stderr)
        return result.stdout

    def module(self, remote, prepare):
        sde = self.config['tofino']
        loaded = remote.ssh('test -d /sys/module/bf_kdrv', check=False).returncode == 0
        device = sde['device_path']
        if loaded:
            remote.ssh('test -e ' + shlex.quote(device))
            # A loaded module must match the running kernel; never replace it automatically.
            module = sde.get('module_path')
            module_command = ('module=' + shlex.quote(module)) if module else 'module=$(find -L "$SDE_INSTALL" -name bf_kdrv.ko -print -quit)'
            remote.ssh(NIX_ENV + sde['sde_command'] + ' --command ' + shlex.quote(
                module_command + '; test -n "$module" && test "$(modinfo -F vermagic "$module" | cut -d" " -f1)" = "$(uname -r)"'))
            return 'bf_kdrv already loaded and device available'
        if not prepare:
            raise RuntimeError('bf_kdrv is not loaded')
        remote.ssh(NIX_ENV + sde['sde_command'] + ' --command ' + shlex.quote(
            'test -x "$SDE_INSTALL/bin/bf_kdrv_mod_load" && sudo -n "$SDE_INSTALL/bin/bf_kdrv_mod_load"'), timeout=120)
        if remote.ssh('test -d /sys/module/bf_kdrv && test -e ' + shlex.quote(device), check=False).returncode:
            raise RuntimeError('bf_kdrv load failed; provide a build matching the running kernel (no kernel upgrade is attempted)')
        return self.module(remote, False)

    def perftest(self, remote, prepare):
        config = self.config['perftest']
        commit = os.environ.get('PERFTEST_COMMIT')
        if not commit:
            commit = logged_run(['git', '-C', str(ROOT / 'experiments/dcn_workload/sources/perftest'), 'rev-parse', 'HEAD']).stdout.strip()
        source = ROOT / 'experiments/dcn_workload/sources/perftest'
        digest = source_digest(source)
        identity = {'commit': commit, 'source_sha256': digest, 'build': config['build_command']}
        base = remote.absolute(config['remote_path'])
        marker = '/.artifact-source.json'
        def matching(path):
            result = remote.ssh('cat ' + shlex.quote(path + marker), check=False)
            try:
                if json.loads(result.stdout) != identity:
                    return False
                return remote.ssh('cd ' + shlex.quote(path) + ' && sha256sum -c .artifact-files.sha256 >/dev/null', check=False).returncode == 0
            except ValueError:
                return False
        destination = base
        if not matching(base):
            if remote.ssh('test -e ' + shlex.quote(base), check=False).returncode == 0:
                destination = base + '-' + commit[:12] + '-' + digest[:8]
            if not matching(destination):
                candidates = remote.ssh('find ' + shlex.quote(str(Path(base).parent)) + ' -maxdepth 1 -type d -name ' + shlex.quote(Path(destination).name + '-*'), check=False).stdout.splitlines()
                candidate = next((p for p in sorted(candidates) if matching(p)), None)
                if candidate:
                    destination = candidate
                elif not prepare:
                    raise RuntimeError('Pinned perftest source/build absent at ' + destination)
                if not candidate:
                    if remote.ssh('test -e ' + shlex.quote(destination), check=False).returncode == 0:
                        destination += '-' + __import__('uuid').uuid4().hex[:8]
                    self.packages(remote, config['build_packages'], True)
                    if self.config['rdma']['stack'] == 'inbox' and remote.ssh('command -v ofed_info', check=False).returncode != 0:
                        self.packages(remote, ['libibverbs-dev', 'librdmacm-dev'], True)
                    remote.ssh('pkg-config --exists libibverbs librdmacm')
                    remote.sync_local_to_remote(source, destination)
                    checksums = ''.join(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' +
                                        str(file.relative_to(source)) + '\n'
                                        for file in sorted(source.rglob('*'))
                                        if file.is_file() and not {'.git', '.github'} & set(file.relative_to(source).parts))
                    remote.ssh('cd ' + shlex.quote(destination) + ' && printf %s ' + shlex.quote(checksums) + ' | sha256sum -c - >/dev/null')
                    remote.ssh('cd ' + shlex.quote(destination) + ' && ' + config['build_command'], timeout=900)
                    relative_files = [str(p.relative_to(source)) for p in sorted(source.rglob('*')) if p.is_file() and not {'.git', '.github'} & set(p.relative_to(source).parts)]
                    remote.ssh('cd ' + shlex.quote(destination) + ' && sha256sum ' + shlex.join(relative_files + ['ib_write_bw', 'ib_write_trace']) + ' > .artifact-files.sha256')
                    remote.ssh('printf %s ' + shlex.quote(json.dumps(identity)) + ' > ' + shlex.quote(destination + marker))
        for binary in ('ib_write_bw', 'ib_write_trace'):
            path = destination + '/' + binary
            remote.ssh('test -x {0} && ! ldd {0} | grep -q "not found"'.format(shlex.quote(path)))
        # The custom parser implements --trace, but this fork's --help does not list it.
        # This path belongs to the upstream submodule, not our P4 source tree.
        remote.ssh('grep -q \'name = "trace"\' ' + shlex.quote(destination + '/src/perftest_parameters.c'))
        self.report['perftest'][remote.target] = dict(identity, path=destination)
        return destination

    def check(self, hosts, switches, prepare=False):
        blocked = {}

        def record(target, item, action):
            # Preparation may mutate devices and deliberately remains fail-fast.
            reason = blocked.get(target.split('/')[0]) or blocked.get('all')
            if reason and not prepare:
                self.report['checks'].append(dict(target=target, item=item, passed=None,
                                                 status='skipped', reason=reason))
                print(f"[{len(self.report['checks'])}] SKIP {target} {item}: {reason}", flush=True)
                self.save()
                return None
            try:
                return self.record(target, item, action)
            except Exception:
                if prepare:
                    raise
                return None

        self.report['fingerprints'] = record('local', 'ssh-agent', lambda: check_agent(self.config['ssh']['expected_fingerprints'])) or []
        if not self.report['checks'][-1]['passed']:
            blocked['all'] = 'SSH agent identity check failed'

        rdma_user = self.config['rdma']['user']
        tofino_user = self.config['tofino']['user']
        targets = {}
        for ip, host in hosts.items():
            targets.setdefault((host.get('user', rdma_user), host['hostname']), 'rdma')
        for name, switch in switches.items():
            targets[(switch.get('user', tofino_user), switch.get('management', name))] = 'tofino'
        for user, hostname in targets:
            remote = RemoteRDMAHelper(user, hostname)
            def connection():
                effective = logged_run(['ssh', *__import__('framework.remote', fromlist=['SSH_OPTIONS']).SSH_OPTIONS, '-G', remote.target]).stdout
                resolved_name = next(line.split()[1] for line in effective.splitlines() if line.startswith('hostname '))
                addresses = sorted({item[4][0] for item in socket.getaddrinfo(resolved_name, 22, type=socket.SOCK_STREAM)})
                routes = [logged_run(['ip', 'route', 'get', address], check=False).stdout for address in addresses]
                return dict(addresses=addresses, routes=routes, identity=remote.ssh('id; uname -r; hostname').stdout)
            record(remote.target, 'management', connection)
            if not self.report['checks'][-1]['passed']:
                blocked[remote.target] = 'Management connection unavailable'
        for (user, hostname), kind in targets.items():
            remote = RemoteRDMAHelper(user, hostname)
            record(remote.target, 'permissions', lambda: remote.ssh('sudo -n -l').stdout)
            record(remote.target, 'packages', lambda: self.packages(remote, self.config['packages'], prepare))
            # Only RDMA endpoints stage traces and measurement logs. Tofino
            # retains the original P4 build/runtime workflow, not a data store.
            if kind == 'rdma':
                def storage():
                    path = remote.absolute(self.config['remote_root'])
                    if prepare:
                        remote.ssh('mkdir -p ' + shlex.quote(path))
                    remote.ssh('test -w ' + shlex.quote(path))
                    available = int(remote.ssh('df -Pk ' + shlex.quote(path) + " | awk 'NR==2 {print $4}'").stdout)
                    if available < self.config['minimum_free_kib']:
                        raise RuntimeError('Insufficient free disk space')
                    return available
                record(remote.target, 'storage', storage)
            if kind == 'tofino':
                record(remote.target, 'nix', lambda: self.nix(remote, prepare))
                record(remote.target, 'sde', lambda: self.sde(remote, prepare))
                record(remote.target, 'bf_kdrv', lambda: self.module(remote, prepare))
            else:
                stack = record(remote.target, 'rdma-stack', lambda: remote.ssh('if command -v ofed_info >/dev/null; then ofed_info -s; else echo inbox; fi').stdout.strip())
                if self.config['rdma']['stack'] == 'inbox' and (stack == 'inbox' or stack is None):
                    record(remote.target, 'rdma-packages', lambda: self.packages(remote, self.config['rdma']['packages'], prepare))
                if prepare and remote.ssh('test -d /sys/module/mlx5_ib && test -d /sys/module/ib_uverbs', check=False).returncode:
                    remote.ssh('sudo -n modprobe mlx5_ib && sudo -n modprobe ib_uverbs')
                for tool in ('ibv_devinfo', 'mlxreg', 'mlnx_qos'):
                    record(remote.target, 'tool:' + tool,
                           lambda tool=tool: remote.ssh('command -v ' + tool).stdout)
                record(remote.target, 'verbs', lambda: remote.ssh('ibv_devinfo').stdout)
                record(remote.target, 'memlock', lambda: remote.ssh('ulimit -l; test "$(ulimit -l)" = unlimited').stdout)
                record(remote.target, 'perftest', lambda: self.perftest(remote, prepare))
        from types import SimpleNamespace
        import copy
        discovered = copy.deepcopy(hosts)
        parser = SimpleNamespace(hosts=discovered, add_host_info=lambda ip, values: discovered[ip].update(values))
        for ip, host in hosts.items():
            remote = RemoteRDMAHelper(host.get('user', rdma_user), host['hostname'], host['eth'], ip)
            record(remote.target + '/' + ip, 'mapping', lambda: remote.get_mellanox_info(parser, require_gid=False))
            record(remote.target + '/' + ip, 'port-inventory',
                   lambda: json.loads(remote.ssh('ip -j address show dev ' + shlex.quote(remote.interface)).stdout))
        self.report['deferred_checks'] = ['Link UP, IP/MTU, RoCE v2 GID and throughput are validated after switch deployment']
        print('DEFER: link/IP/MTU/GID/throughput acceptance until switches are deployed', flush=True)
        self.report['discovered_hosts'] = discovered
        self.save()
        summary = self.report['summary']
        print(f"Environment complete: {summary['passed']} passed, {summary['failed']} failed, "
              f"{summary['skipped']} skipped; report: {self.path}", flush=True)
        if summary['failed'] or summary['skipped']:
            raise CheckFailed(f"Environment check: {summary['passed']} passed, "
                              f"{summary['failed']} failed, {summary['skipped']} skipped; "
                              f"report: {self.path}")
        return self.report
