"""Export the deployment's installed MPI for the controller image build context."""
import argparse
import hashlib
import json
from pathlib import Path

from framework.config import load_deployment
from framework.paths import REPO_ROOT
from framework.remote import RemoteRDMAHelper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', default='deployment/deployment.local.yaml')
    args = parser.parse_args()
    config = load_deployment(args.deployment)
    mpi = config['mpi']
    prefix = Path(mpi['prefix'])
    if str(prefix) != '/usr/mpi/gcc/openmpi-4.1.7rc1':
        raise ValueError('Dockerfile expects /usr/mpi/gcc/openmpi-4.1.7rc1')
    remote = RemoteRDMAHelper(config['rdma']['user'], mpi['launcher'])
    root = REPO_ROOT / 'build/mpi-toolchain'
    target = root / prefix.name
    if target.exists():
        raise ValueError('Toolchain export already exists: ' + str(target))
    target.mkdir(parents=True)
    remote.sync_remote_directory_to_local(str(prefix), target)
    files = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob('*')) if p.is_file()}
    (root / 'manifest.json').write_text(json.dumps(
        dict(host=mpi['launcher'], prefix=str(prefix), files=files), indent=2) + '\n')
    (root / 'SHA256SUMS').write_text(''.join(
        f'{checksum}  {prefix.name}/{name}\n' for name, checksum in files.items()))
    print('Exported MPI toolchain:', target)


if __name__ == '__main__':
    main()
