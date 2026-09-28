"""Exercise actual path/checksum commands without SSH or package installation."""
from contextlib import ExitStack
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from framework.environment import Environment


class LocalRemote:
    target = 'test@fixture'

    def __init__(self):
        self.transfers = 0

    def absolute(self, path):
        return path

    def ssh(self, command, timeout=60, check=True):
        # Toolchain provisioning is outside this filesystem regression fixture.
        if command == 'pkg-config --exists libibverbs librdmacm':
            return subprocess.CompletedProcess(command, 0, '', '')
        return subprocess.run(['bash', '-c', 'set -euo pipefail; ' + command],
                              capture_output=True, text=True, timeout=timeout, check=check)

    def sync_local_to_remote(self, source, destination):
        self.transfers += 1
        shutil.copytree(source, destination)


class PerftestPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        source = self.root / 'experiments/dcn_workload/sources/perftest'
        (source / 'src').mkdir(parents=True)
        (source / 'src/perftest_parameters.c').write_text('name = "trace";\n')
        remote_parent = self.root / 'remote'
        remote_parent.mkdir()
        self.base = remote_parent / 'perftest'
        config = {'perftest': {'remote_path': str(self.base), 'build_packages': [],
                              'build_command': 'cp /bin/true ib_write_bw && cp /bin/true ib_write_trace'},
                  'rdma': {'stack': 'existing'}}
        self.environment = Environment(config, self.root / 'report.json')
        self.remote = LocalRemote()
        self.stack.enter_context(patch('framework.environment.ROOT', self.root))
        self.stack.enter_context(patch.dict('os.environ', {'PERFTEST_COMMIT': '253a6c620ebbc0181ea366b088b2ab67572b9ce1'}))
        self.packages = self.stack.enter_context(patch.object(self.environment, 'packages'))

    def test_prepare_builds_missing_source_and_checks_upstream_trace_path(self):
        destination = Path(self.environment.perftest(self.remote, prepare=True))
        self.assertTrue((destination / 'src/perftest_parameters.c').is_file())
        self.assertTrue((destination / 'ib_write_trace').is_file())
        self.assertEqual(self.remote.transfers, 1)
        self.assertEqual(self.environment.report['perftest'][self.remote.target]['path'], str(destination))

    def test_check_reports_missing_installation_without_modifying_it(self):
        with self.assertRaisesRegex(RuntimeError, 'Pinned perftest source/build absent'):
            self.environment.perftest(self.remote, prepare=False)
        self.assertEqual(self.remote.transfers, 0)
        self.assertFalse(self.base.exists())
        self.packages.assert_not_called()

    def test_valid_installation_is_reused_by_check_and_prepare(self):
        first = self.environment.perftest(self.remote, prepare=True)
        self.packages.reset_mock()
        for prepare in (False, True):
            self.assertEqual(self.environment.perftest(self.remote, prepare=prepare), first)
        self.assertEqual(self.remote.transfers, 1)
        self.packages.assert_not_called()

    def test_prepare_repairs_corruption_in_a_new_directory(self):
        first = Path(self.environment.perftest(self.remote, prepare=True))
        (first / 'ib_write_trace').write_text('corrupt')
        with self.assertRaisesRegex(RuntimeError, 'Pinned perftest source/build absent'):
            self.environment.perftest(self.remote, prepare=False)
        repaired = Path(self.environment.perftest(self.remote, prepare=True))
        self.assertNotEqual(first, repaired)
        self.assertEqual((first / 'ib_write_trace').read_text(), 'corrupt')
        self.assertEqual((repaired / 'ib_write_trace').read_bytes(), Path('/bin/true').read_bytes())
        self.assertEqual(self.remote.transfers, 2)
