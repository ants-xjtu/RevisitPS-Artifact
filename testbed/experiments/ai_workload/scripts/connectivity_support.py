"""Deployment/build adapters for the standalone MPI pair connectivity script."""
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import sys

import yaml

from framework.config import load_deployment
from framework.paths import REPO_ROOT as ROOT
from framework.remote import RemoteRDMAHelper, find_roce_v2_gid, ssh_spacing
from experiments.ai_workload.scripts.build import (
    BINARIES, build, distribute, target_environments,
)


def deployment():
    default = ROOT / 'deployment/deployment.local.yaml'
    return load_deployment(os.environ.get(
        'ARTIFACT_DEPLOYMENT', str(default if default.exists() else ROOT / 'deployment/deployment.yaml')))


def inventory():
    return yaml.safe_load((ROOT / 'deployment/hosts.yaml').read_text())['hosts']


def endpoint(value):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+', value):
        raise ValueError('Expected endpoint host:device: ' + value)
    return value.split(':')


def remote(host, config):
    users = {row.get('user', config['rdma']['user']) for row in inventory().values()
             if row['hostname'] == host}
    if len(users) != 1:
        raise ValueError('Expected one inventory SSH user for host: ' + host)
    return RemoteRDMAHelper(users.pop(), host)


def prepare(args, config):
    workload, endpoints_file, skip_build, skip_sync, custom = args
    hosts = {endpoint(line.strip())[0] for line in Path(endpoints_file).read_text().splitlines()
             if line.strip()}
    hosts.add(config['mpi']['launcher'])
    remotes = {host: remote(host, config) for host in sorted(hosts)}
    if custom:
        binary = Path(custom).resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('Binary not executable: ' + str(binary))
        if skip_sync == '1':
            return str(binary)
        from framework.results import digest
        checksum = digest(binary)
        destination = config['mpi']['remote_root'].rstrip('/') + '/connectivity/' + checksum
        with tempfile.TemporaryDirectory(prefix='connectivity-binary-') as temporary:
            shutil.copy2(binary, Path(temporary) / binary.name)
            for helper in remotes.values():
                helper.sync_local_to_remote(Path(temporary), destination)
                helper.ssh('cd ' + shlex.quote(destination) + ' && printf %s ' +
                           shlex.quote(checksum + '  ' + binary.name + '\n') + ' | sha256sum -c -')
        return destination + '/' + binary.name
    targets = target_environments(config['mpi'], remotes)
    cache, saved = build(workload, config['mpi'], targets, allow_build=skip_build != '1')
    directory = str(cache) if skip_sync == '1' else distribute(cache, saved, config['mpi'], remotes)
    return directory + '/' + BINARIES[workload]


def gid(value, config):
    host, device = endpoint(value)
    ips = [ip for ip, row in inventory().items()
           if row['hostname'] == host and row['mlx_device_name'] == device]
    if len(ips) != 1:
        raise ValueError('Expected one inventory IP for endpoint: ' + value)
    prefix = '/sys/class/infiniband/' + device + '/ports/1'
    command = (f'for f in {prefix}/gids/*; do printf "%s %s %s\\n" '
               f'"${{f##*/}}" "$(cat "$f")" "$(cat {prefix}/gid_attrs/types/${{f##*/}})"; done')
    return find_roce_v2_gid(remote(host, config).ssh(command).stdout, ips[0])


def launch(args, config):
    seconds = int(args[0])
    if seconds <= 0:
        raise ValueError('Timeout must be positive')
    mpi = config['mpi']
    command = ['timeout', '--kill-after=5s', str(seconds) + 's',
               str(Path(mpi['prefix']) / 'bin/mpirun'), '--prefix', mpi['prefix'],
               '-x', 'LD_LIBRARY_PATH', *args[1:]]
    environment = ('export LD_LIBRARY_PATH=' + shlex.quote(mpi['library_path']) +
                   '${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; ')
    result = remote(mpi['launcher'], config).ssh(
        environment + shlex.join(command), timeout=seconds + 30, check=False)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def main():
    action, *args = sys.argv[1:]
    config = deployment()
    with ssh_spacing():
        if action == 'prepare':
            print(prepare(args, config))
        elif action == 'gid':
            print(gid(args[0], config))
        elif action == 'launch':
            return launch(args, config)
        else:
            raise ValueError('Unknown action: ' + action)
    return 0


if __name__ == '__main__':
    sys.exit(main())
