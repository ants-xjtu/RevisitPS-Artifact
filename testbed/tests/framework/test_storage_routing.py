"""Verify that switch deployment cannot transfer staged experimental data."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from switches.remote import RemoteTofinoHelper


class StorageRoutingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('rsync'), 'requires rsync')
    def test_switch_sync_excludes_measurements_even_without_configured_excludes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'source', Path(directory) / 'switch'
            excluded = ['data/raw/result.csv', 'trace/traffic.trace', 'logs/runtime.log',
                        'results/dcn_workload/run/parsed/fct.json',
                        'results/dcn_workload/run/configs/snapshot.yaml',
                        'results/dcn_workload/run/figures/figure2.pdf']
            included = ['switches/programs/leaf/program.p4', 'switches/bfrt/controller.py',
                        'switches/scripts/wait_port.sh', 'deployment/topologies/topology.yaml']
            for name in excluded + included:
                file = source / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(name)
            destination.mkdir()
            helper = RemoteTofinoHelper.__new__(RemoteTofinoHelper)
            helper.remote = Mock(target='test@switch')
            helper.remote_cwd = '/home/test/testbed'
            with patch('switches.remote.logged_run') as run:
                helper.sync_repo(source, [])
            argv = run.call_args.args[0]
            filters = [argument for argument in argv if argument.startswith('--exclude=')]
            # Exercise rsync's actual pattern matching, not just string presence.
            subprocess.run(['rsync', '-a', *filters, str(source) + '/', str(destination) + '/'], check=True)
            self.assertEqual(sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()),
                             sorted(included))
