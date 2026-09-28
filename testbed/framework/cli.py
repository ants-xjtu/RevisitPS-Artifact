"""Unified DCN and AI experiment entry point."""
import argparse
import os
import re
import sys
from framework.paths import REPO_ROOT as ROOT


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.chdir(ROOT)
    if argv and argv[0] == 'nic':
        from framework.rdma.config_nic import main as nic
        from framework.runner import device_lock
        with device_lock():
            return nic(argv[1:])
    if argv and argv[0] == 'diagnose':
        from framework.diagnostics import main as diagnose
        from framework.runner import device_lock
        with device_lock():
            return diagnose.main(args=argv[1:], standalone_mode=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', choices=['dcn_workload', 'ai_workload'], required=True)
    parser.add_argument('--network-mode', choices=['lossless', 'lossy', 'all'], default='all')
    parser.add_argument('--workload', choices=['ring_allreduce', 'alltoall', 'alltoallv', 'all'], default='all')
    parser.add_argument('--stage', choices=['prepare', 'check', 'run', 'parse', 'plot', 'status', 'all'], default='all')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--refresh-environment', action='store_true')
    parser.add_argument('--deployment', default='deployment/deployment.yaml')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id) or args.repeat < 1:
        parser.error('run-id must contain only letters/digits/_/- and repeat must be positive')
    from framework import runner
    if args.experiment == 'ai_workload':
        return runner.run_ai(args)
    command = ['--experiment', args.network_mode, '--stage', args.stage, '--run-id', args.run_id,
               '--repeat', str(args.repeat), '--deployment', args.deployment]
    command += [flag for flag, enabled in [('--resume', args.resume), ('--dry-run', args.dry_run),
                ('--refresh-environment', args.refresh_environment)] if enabled]
    return runner.main(command)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'testbed: {error}', file=sys.stderr)
        sys.exit(1)
