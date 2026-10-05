"""Export the deployment's installed MPI for the controller image build context."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

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
    if root.exists():
        raise ValueError('Toolchain export already exists: ' + str(root))
    root.parent.mkdir(parents=True, exist_ok=True)
    # Publish the toolchain and its checksums together, only after a complete export.
    with tempfile.TemporaryDirectory(prefix='.mpi-toolchain-', dir=root.parent) as temporary:
        staged = Path(temporary) / 'export'
        staged_target = staged / prefix.name
        staged_target.mkdir(parents=True)
        remote.sync_remote_directory_to_local(str(prefix), staged_target)
        files = {str(p.relative_to(staged_target)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(staged_target.rglob('*')) if p.is_file()}
        if not files or not (staged_target / 'bin/mpicxx').is_file():
            raise ValueError('Exported MPI toolchain is incomplete: missing bin/mpicxx')
        (staged / 'manifest.json').write_text(json.dumps(
            dict(host=mpi['launcher'], prefix=str(prefix), files=files), indent=2) + '\n')
        (staged / 'SHA256SUMS').write_text(''.join(
            f'{checksum}  {prefix.name}/{name}\n' for name, checksum in files.items()))
        staged.rename(root)
    print('Exported MPI toolchain:', target)


if __name__ == '__main__':
    main()
