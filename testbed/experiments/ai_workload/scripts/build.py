"""Content-addressed container builds; direct distribution to all MPI nodes."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from framework.paths import REPO_ROOT as ROOT
from framework.remote import logged_run

BINARIES = {'ring_allreduce': 'mpi_verbs_p2p_ring4', 'alltoall': 'mpi_verbs_global_alltoall',
            'alltoallv': 'mpi_verbs_global_alltoallv',
            'connectivity_ring': 'mpi_verbs_ringallreduce'}
SOURCES = ROOT / 'experiments/ai_workload/sources'
PROBE = r'''#include <mpi.h>
#include <infiniband/verbs.h>
#include <rdma/rdma_cma.h>
#include <cstdio>
int main(int argc, char **argv) {
 MPI_Init(&argc, &argv);
 char version[MPI_MAX_LIBRARY_VERSION_STRING]; int length=0, n=0;
 MPI_Get_library_version(version, &length); std::printf("%s\n",version);
 auto devices=ibv_get_device_list(&n); if(devices) ibv_free_device_list(devices);
 auto contexts=rdma_get_devices(&n); if(contexts) rdma_free_devices(contexts);
 MPI_Finalize(); return 0;
}
'''


def mpi_version(output):
    match = re.search(r'Open MPI[^\n]*?\b(\d+\.\d+\.\d+(?:(?:rc|a|b)\d+)?)', output)
    if not match:
        raise ValueError('An explicit Open MPI toolchain is required: ' + output[:200])
    return match[1]


def target_environments(mpi, remotes):
    """Read actual runtimes, not hostnames or a perftest readiness cache."""
    prefix = Path(mpi['prefix'])
    if not prefix.is_absolute() or not Path(mpi['remote_root']).is_absolute():
        raise ValueError('mpi.prefix and mpi.remote_root must be absolute remote paths')
    command = ('uname -m; getconf GNU_LIBC_VERSION; ' +
               shlex.quote(str(prefix / 'bin/mpirun')) + ' --version; ' +
               r'ldconfig -p | grep -E "libstdc\+\+|libibverbs|librdmacm|libmpi\.so"; ' +
               'test "$(ulimit -l)" = unlimited; lscpu -p=CPU,CORE,SOCKET,ONLINE')
    return {host: remote.ssh(command).stdout for host, remote in remotes.items()}


def toolchain_identity(mpi):
    compiler = mpi['compiler']
    compiler_info = logged_run([compiler, '--showme']).stdout
    return {'compiler': compiler, 'command': compiler_info,
                 'version': logged_run([compiler, '--version']).stdout,
                 'mpi': logged_run([compiler, '--showme:version']).stdout,
                 'architecture': logged_run(['uname', '-m']).stdout.strip(),
                 'glibc': logged_run(['getconf', 'GNU_LIBC_VERSION']).stdout.strip(),
                 'libraries': logged_run(['ldconfig', '-p']).stdout,
                 'image': os.environ.get('ARTIFACT_IMAGE_ID', 'native')}


def build(workload, mpi, targets, *, allow_build=True):
    from framework.results import atomic_json, canonical_hash, digest
    compiler = mpi['compiler']
    flags = list(mpi['compile_flags'])
    toolchain = toolchain_identity(mpi)
    local_mpi = mpi_version(toolchain['mpi'])
    local_glibc = tuple(map(int, toolchain['glibc'].split()[-1].split('.')))
    for host, description in targets.items():
        rows = description.splitlines()
        if rows[0] != toolchain['architecture'] or mpi_version(description) != local_mpi:
            raise ValueError(f'{host}: CPU/Open MPI mismatch; configure a matching container toolchain')
        if tuple(map(int, rows[1].split()[-1].split('.'))) < local_glibc:
            raise ValueError(f'{host}: glibc is older than the build container; select a matching image')
    files = [SOURCES / (BINARIES[workload] + '.cpp')]
    if workload == 'alltoallv':
        files += [SOURCES / 'zipfian_incast_pattern.cpp']
    identity = dict(workload=workload, source={p.name: digest(p) for p in SOURCES.iterdir() if p.is_file()},
                    flags=flags, libraries=['ibverbs', 'rdmacm'], toolchain=toolchain,
                    targets=targets, probe=PROBE, implementation=digest(Path(__file__)))
    key = canonical_hash(identity)
    cache = ROOT / 'build/ai_workload' / key
    marker = cache / 'build.json'
    if marker.exists():
        saved = json.loads(marker.read_text())
        if saved['identity'] == identity and all((cache / name).is_file() and digest(cache / name) == value for name, value in saved['files'].items()):
            return cache, saved
        raise ValueError('AI build cache checksum mismatch; remove the corrupt cache directory: ' + str(cache))
    if not allow_build:
        raise ValueError('No matching AI build cache; run without --skip-build')
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=key + '-', dir=cache.parent))
    try:
        with (temporary / 'build.log').open('w') as log:
            subprocess.run([compiler, *flags, '-o', str(temporary / BINARIES[workload]),
                            *map(str, files), '-libverbs', '-lrdmacm'], check=True, timeout=900,
                           stdout=log, stderr=subprocess.STDOUT)
            (temporary / 'probe.cpp').write_text(PROBE)
            subprocess.run([compiler, *flags, '-o', str(temporary / 'runtime_probe'),
                            str(temporary / 'probe.cpp'), '-libverbs', '-lrdmacm'], check=True, timeout=120,
                           stdout=log, stderr=subprocess.STDOUT)
        saved = dict(identity=identity, key=key,
                     files={name: digest(temporary / name) for name in (BINARIES[workload], 'runtime_probe')})
        atomic_json(temporary / 'build.json', saved)
        temporary.rename(cache)
    except BaseException as error:
        if temporary.exists():
            failure = temporary.with_name('failed-' + temporary.name)
            temporary.rename(failure)
            raise RuntimeError(f'AI build failed; inspect {failure / "build.log"}') from error
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return cache, saved


def distribute(cache, saved, mpi, remotes):
    destination = mpi['remote_root'].rstrip('/') + '/build/' + saved['key']
    checksums = ''.join(f'{value}  {name}\n' for name, value in saved['files'].items())
    for remote in remotes.values():
        remote.sync_local_to_remote(cache, destination)
        q = shlex.quote
        remote.ssh('cd ' + q(destination) + ' && printf %s ' + q(checksums) + ' | sha256sum -c -')
        # Both versioned ELF dependencies and a short MPI/C++/RDMA program must work.
        environment = 'export LD_LIBRARY_PATH=' + q(mpi['library_path']) + '${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; '
        for name in saved['files']:
            binary = q(destination + '/' + name)
            output = remote.ssh(environment + 'ldd ' + binary).stdout
            if 'not found' in output:
                raise ValueError(f'{remote.target}: incompatible runtime dependencies: {output}')
        remote.ssh(environment + q(destination + '/runtime_probe'), timeout=60)
    return destination
