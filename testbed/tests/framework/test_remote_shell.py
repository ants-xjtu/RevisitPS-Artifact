"""Execute the SSH shell payload locally with a failing login-shell exit hook."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framework.remote import RemoteRDMAHelper


class RemoteShellTests(unittest.TestCase):
    def setUp(self):
        self.remote = RemoteRDMAHelper('test', 'unused-host')
        self.runner = patch('framework.remote.logged_run', side_effect=self.run_locally)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def run_locally(self, argv, timeout=60, check=True):
        # A deterministic equivalent of a login exit hook overriding status.
        # Also ensure the replacement shell inherits the login environment.
        shell = shlex.split(argv[-1])
        shell[-1] = "trap 'exit 99' EXIT; export ARTIFACT_LOGIN_TEST='login environment'; " + shell[-1]
        result = subprocess.run(shell, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f'exited {result.returncode}: {result.stderr}')
        return result

    def test_success_preserves_login_environment_and_quoting(self):
        text = 'spaces; dollar $ sign and single quote: \' '
        result = self.remote.ssh('printf "%s\\n%s" "$ARTIFACT_LOGIN_TEST" ' + shlex.quote(text) + '; exit 0')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'login environment\n' + text)

    def test_real_failure_status_is_preserved(self):
        self.assertEqual(self.remote.ssh('exit 7', check=False).returncode, 7)
        with self.assertRaisesRegex(RuntimeError, 'exited 7'):
            self.remote.ssh('exit 7')

    def test_strict_shell_options_still_detect_errors(self):
        for command in ('false; echo should-not-run', 'false | true; echo should-not-run',
                        'unset ARTIFACT_UNSET_TEST; echo "$ARTIFACT_UNSET_TEST"'):
            with self.subTest(command=command):
                result = self.remote.ssh(command, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(result.returncode, 99)
                self.assertNotIn('should-not-run', result.stdout)

    def test_process_start_pid_check_and_wait(self):
        with tempfile.TemporaryDirectory(prefix='artifact shell ') as folder:
            log = Path(folder) / "receiver's log"
            proc = self.remote.start('printf receiver-started', str(log))
            self.assertTrue(Path(proc['state'] + '.pid').read_text().strip())
            self.assertEqual(self.remote.wait(proc, timeout=5), 0)
            self.assertEqual(log.read_text(), 'receiver-started')

    def test_cleanup_missing_process_returns_success(self):
        with tempfile.TemporaryDirectory() as folder:
            self.remote.stop({'state': str(Path(folder) / 'missing'), 'token': 'unused'})
