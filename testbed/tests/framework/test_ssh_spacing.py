import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framework.remote import logged_run, ssh_spacing


class SSHSpacingTests(unittest.TestCase):
    def test_spacing_across_hosts_errors_and_local_commands(self):
        now = [0.0]
        starts = []

        def run(argv, **kwargs):
            starts.append((argv[0], now[0]))
            now[0] += 0.25
            return subprocess.CompletedProcess(argv, 255 if 'bad' in argv else 0, '', '')

        with patch.dict(os.environ, {'ARTIFACT_COMMAND_LOG': ''}), \
             patch('framework.remote.time.monotonic', side_effect=lambda: now[0]), \
             patch('framework.remote.time.sleep', side_effect=lambda delay: now.__setitem__(0, now[0] + delay)), \
             patch('framework.remote.subprocess.run', side_effect=run):
            with ssh_spacing(1):
                logged_run(['ssh', 'dc20', 'true'])
                logged_run(['ssh', '-G', 'dc21'])
                logged_run(['ip', 'route'])
                with self.assertRaises(RuntimeError):
                    logged_run(['ssh', 'bad', 'true'])
                logged_run(['ssh', 'dc22', 'true'])
            logged_run(['ssh', 'dc23', 'true'])
        self.assertEqual([start for _, start in starts], [0, .25, .5, 1.25, 2.5, 2.75])

    def test_timeout_also_spaces_next_request_and_restores_context(self):
        with patch.dict(os.environ, {'ARTIFACT_COMMAND_LOG': ''}), \
             patch('framework.remote.time.monotonic', return_value=10), \
             patch('framework.remote.time.sleep') as sleep, \
             patch('framework.remote.subprocess.run', side_effect=[
                 subprocess.TimeoutExpired(['ssh'], 10),
                 subprocess.CompletedProcess(['ssh'], 0, '', ''),
                 subprocess.CompletedProcess(['ssh'], 0, '', '')]):
            with ssh_spacing(1):
                with self.assertRaises(subprocess.TimeoutExpired):
                    logged_run(['ssh', 'dc20'])
                logged_run(['ssh', 'dc21'])
            logged_run(['ssh', 'dc22'])
            sleep.assert_called_once_with(1)
