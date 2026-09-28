"""Replace a previous switchd only after it has exited; no real signals/SSH."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from switches.remote import RemoteTofinoHelper, STOP_SWITCHD


class SwitchReplacementTests(unittest.TestCase):
    def run_stop_script(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tool = root / 'fake-tool'
            tool.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
root = pathlib.Path(os.environ['SWITCH_TEST_ROOT'])
mode = os.environ['SWITCH_TEST_MODE']
command = pathlib.Path(sys.argv[0]).name
if command == 'pgrep':
    assert sys.argv[1:] == ['-x', 'bf_switchd']
    if mode == 'query-error': sys.exit(2)
    if mode == 'none' or (root / 'gone').exists(): sys.exit(1)
    print('4321')
elif command == 'cat':
    print('bf_switchd')
elif command == 'sudo':
    assert sys.argv[1:3] == ['-n', 'kill']
    assert sys.argv[4:] == ['--', '4321']
    with (root / 'signals').open('a') as out: out.write(sys.argv[3] + '\\n')
    if mode == 'denied': sys.exit(1)
    if mode == 'graceful' or (mode == 'forced' and sys.argv[3] == '-KILL'):
        (root / 'gone').touch()
elif command != 'sleep':
    raise AssertionError(command)
''')
            tool.chmod(0o755)
            for name in ('pgrep', 'cat', 'sudo', 'sleep'):
                (root / name).symlink_to(tool)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       SWITCH_TEST_ROOT=str(root), SWITCH_TEST_MODE=mode)
            result = subprocess.run(['bash', '-c', 'set -euo pipefail; ' + STOP_SWITCHD],
                                    env=env, text=True, capture_output=True, timeout=30)
            signals = (root / 'signals').read_text().splitlines() if (root / 'signals').exists() else []
            return result, signals

    def test_existing_daemon_gets_term_before_new_start(self):
        result, signals = self.run_stop_script('graceful')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(signals, ['-TERM'])

    def test_stubborn_daemon_gets_kill_after_term(self):
        result, signals = self.run_stop_script('forced')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(signals, ['-TERM', '-KILL'])

    def test_no_daemon_requires_no_signal(self):
        result, signals = self.run_stop_script('none')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(signals, [])

    def test_failed_cleanup_aborts(self):
        for mode in ('query-error', 'denied', 'survives'):
            with self.subTest(mode=mode):
                result, _ = self.run_stop_script(mode)
                self.assertNotEqual(result.returncode, 0)

    def helper(self, root):
        helper = RemoteTofinoHelper.__new__(RemoteTofinoHelper)
        helper.log_dir = root
        helper.remote_cwd = '/home/test/testbed'
        helper.remote = Mock(target='test@sw1')
        helper.remote.ssh.return_value = subprocess.CompletedProcess([], 0, '123', '')
        helper.switch_id = 'sw1'
        helper.run_id = 'new-run'
        helper.session = 'artifact-new-run-sw1'
        return helper

    def test_unowned_switchd_is_stopped_before_console_launch(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), \
                patch('switches.remote.logged_run') as local:
            helper = self.helper(Path(folder))
            events = []
            helper.remote.ssh.side_effect = lambda command, **kw: (
                events.append(command) or subprocess.CompletedProcess([], 0, '123', ''))
            local.side_effect = lambda command, **kw: events.append(command)
            helper.remote_deploy('run_switchd.sh -p {{p4program_name}}', 'bigswitch')
            self.assertEqual(events[0], STOP_SWITCHD)
            self.assertEqual(events[1][:2], ['tmux', 'new-session'])
            self.assertTrue((Path(folder) / 'sw1.owner.json').is_file())

    def test_ssh_cleanup_failure_prevents_console_launch(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), \
                patch('switches.remote.logged_run') as local:
            helper = self.helper(Path(folder))
            helper.remote.ssh.side_effect = RuntimeError('SSH failed')
            with self.assertRaisesRegex(RuntimeError, 'SSH failed'):
                helper.remote_deploy('run_switchd.sh -p {{p4program_name}}', 'bigswitch')
            local.assert_not_called()


if __name__ == '__main__':
    unittest.main()
