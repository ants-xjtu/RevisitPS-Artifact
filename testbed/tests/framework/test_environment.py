import os
import json
import io
import subprocess
from contextlib import redirect_stdout
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.environment import Environment, CheckFailed, check_agent
from framework.nix_environment import NIX_ENV, NIX_PING, NIX_START
from framework.remote import RemoteRDMAHelper


def result(code=0, output=''):
    return SimpleNamespace(returncode=code, stdout=output, stderr='')


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = Environment({'tofino': {'device_path': '/dev/bf0', 'sde_command': 'sde-env'}}, Path(self.folder.name) / 'environment.json')

    def test_agent_socket_missing(self):
        with patch.dict(os.environ, {'SSH_AUTH_SOCK': '/does/not/exist'}):
            with self.assertRaisesRegex(RuntimeError, 'socket'):
                check_agent(['SHA256:expected'])

    def test_nix_missing_never_installs(self):
        remote = Mock()
        remote.ssh.return_value = result(1)
        with self.assertRaisesRegex(RuntimeError, 'administrator'):
            self.env.nix(remote, prepare=True)
        commands = [call.args[0] for call in remote.ssh.call_args_list]
        self.assertFalse(any('install' in cmd or 'curl' in cmd or 'apt-get' in cmd for cmd in commands))

    def test_package_check_is_read_only(self):
        remote = Mock()
        remote.ssh.return_value = result(output='rsync\n')
        with self.assertRaisesRegex(RuntimeError, 'Missing packages'):
            self.env.packages(remote, ['rsync'], False)
        self.assertFalse(any('apt-get' in call.args[0] for call in remote.ssh.call_args_list))

    def test_package_prepare_rechecks(self):
        remote = Mock()
        remote.ssh.side_effect = [result(output='rsync\n'), result(), result(), result(output='rsync\n')]
        with self.assertRaisesRegex(RuntimeError, 'Missing packages'):
            self.env.packages(remote, ['rsync'], True)
        self.assertEqual(sum('apt-get install' in call.args[0] for call in remote.ssh.call_args_list), 1)

    def test_existing_packages_are_not_installed(self):
        remote = Mock()
        remote.ssh.return_value = result()
        self.env.packages(remote, ['rsync'], True)
        self.assertEqual(remote.ssh.call_count, 1)

    def test_package_ssh_failure_is_not_missing_or_installed(self):
        remote = Mock()
        remote.ssh.side_effect = [result(255)]
        with self.assertRaisesRegex(RuntimeError, 'Package checks incomplete'):
            self.env.packages(remote, ['rsync', 'python3'], True)
        self.assertEqual(remote.ssh.call_count, 1)
        self.assertFalse(any('apt-get' in c.args[0] for c in remote.ssh.call_args_list))

    def test_nix_healthy_daemon_does_not_need_systemd(self):
        remote = Mock()
        remote.ssh.side_effect = [result(), result(), result(output='Nix 2.32.4')]
        self.assertEqual(self.env.nix(remote, True), 'Nix 2.32.4')
        self.assertFalse(any('systemctl' in c.args[0] for c in remote.ssh.call_args_list))

    def test_nix_check_does_not_start_daemon(self):
        remote = Mock()
        remote.ssh.side_effect = [result(), result(1)]
        with self.assertRaisesRegex(RuntimeError, 'run prepare'):
            self.env.nix(remote, False)
        self.assertEqual(remote.ssh.call_count, 2)

    def test_nix_prepare_starts_existing_daemon_and_verifies(self):
        remote = Mock()
        remote.ssh.side_effect = [result(), result(1), result(), result(), result(output='Nix')]
        self.assertEqual(self.env.nix(remote, True), 'Nix')
        self.assertEqual(remote.ssh.call_args_list[2].args[0], NIX_START)
        self.assertEqual(remote.ssh.call_args_list[3].args[0], NIX_PING)

    def test_nix_failed_startup_verification_is_not_success(self):
        remote = Mock()
        remote.ssh.side_effect = [result(), result(1), result()] + [result(1)] * 10
        with patch('framework.environment.time.sleep'), self.assertRaisesRegex(RuntimeError, 'after startup'):
            self.env.nix(remote, True)

    def test_nix_path_restored_despite_inherited_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / '.nix-profile/bin/nix'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\necho nix-found\n')
            binary.chmod(0o700)
            output = subprocess.run(['bash', '-c', NIX_ENV + 'nix'],
                env=dict(os.environ, HOME=folder, PATH='/usr/bin:/bin', __ETC_PROFILE_NIX_SOURCED='1'),
                capture_output=True, text=True, check=True)
            self.assertEqual(output.stdout.strip(), 'nix-found')

    def test_predeployment_mapping_does_not_require_gid(self):
        remote = RemoteRDMAHelper('user', 'host', 'eth0', '10.0.0.1')
        parser = SimpleNamespace(hosts={'10.0.0.1': {}}, add_host_info=Mock())
        with patch.object(remote, 'ssh', side_effect=[result(output='mlx5_0 eth0\n'),
                                                     result(output='bus-info: 0000:01:00.0\n')]) as ssh:
            remote.get_mellanox_info(parser, require_gid=False)
        self.assertEqual(ssh.call_count, 2)
        self.assertIsNone(remote.gid)

    def test_loaded_module_is_not_reloaded(self):
        remote = Mock()
        remote.ssh.return_value = result()
        self.env.module(remote, True)
        self.assertFalse(any('bf_kdrv_mod_load' in call.args[0] for call in remote.ssh.call_args_list))

    def test_missing_module_check_does_not_load(self):
        remote = Mock()
        remote.ssh.return_value = result(1)
        with self.assertRaisesRegex(RuntimeError, 'not loaded'):
            self.env.module(remote, False)
        self.assertEqual(remote.ssh.call_count, 1)


class CompleteCheckTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.env = Environment({
            'ssh': {'expected_fingerprints': ['SHA256:test']},
            'rdma': {'user': 'test', 'stack': 'existing'},
            'tofino': {'user': 'test'}, 'packages': ['util-linux'],
            'remote_root': 'artifact', 'minimum_free_kib': 1,
        }, Path(folder) / 'environment.json')
        self.hosts = {f'10.0.0.{i}': {'hostname': f'dc{i}', 'eth': 'eth0'}
                      for i in range(20, 24)}
        self.commands = []
        self.offline = set()
        self.missing_packages = set()

        def helper(user, hostname, *args):
            remote = Mock(target=f'{user}@{hostname}', interface='eth0')
            remote.absolute.return_value = '/home/test/artifact'

            def ssh(command, **kwargs):
                self.commands.append((hostname, command))
                if hostname in self.offline:
                    raise RuntimeError('Connection unavailable')
                if 'dpkg-query' in command:
                    return result(output='util-linux\n' if hostname in self.missing_packages else '')
                if command.startswith('df '):
                    return result(output='1000')
                if 'ofed_info' in command:
                    return result(output='inbox')
                if command.startswith('ip -j address'):
                    return result(output='[{"operstate":"DOWN","mtu":1500,"addr_info":[]}]')
                return result()

            remote.ssh.side_effect = ssh
            remote.get_mellanox_info.return_value = None
            return remote

        self.stack.enter_context(patch('framework.environment.RemoteRDMAHelper', side_effect=helper))
        self.agent = self.stack.enter_context(patch('framework.environment.check_agent', return_value=['SHA256:test']))
        self.stack.enter_context(patch('framework.environment.logged_run', return_value=result(output='hostname example\n')))
        self.stack.enter_context(patch('framework.environment.socket.getaddrinfo', return_value=[(0, 0, 0, '', ('127.0.0.1', 22))]))
        self.stack.enter_context(patch('framework.rdma.config_nic.probe_port', return_value={'state': 'UP'}))
        for method in ('perftest', 'nix', 'sde', 'module'):
            self.stack.enter_context(patch.object(self.env, method, return_value='available'))

    def test_dependency_failures_do_not_hide_other_hosts_or_checks(self):
        self.missing_packages = {'dc20', 'dc22'}
        with self.assertRaises(CheckFailed):
            self.env.check(self.hosts, {'sw1': {}})
        report = json.loads(self.env.path.read_text())
        failed = {(c['target'], c['item']) for c in report['checks'] if c['status'] == 'failed'}
        self.assertEqual(failed, {('test@dc20', 'packages'), ('test@dc22', 'packages')})
        self.assertEqual(report['summary']['failed'], 2)
        self.assertEqual(report['summary']['skipped'], 0)
        for hostname in ('dc20', 'dc21', 'dc22', 'dc23'):
            self.assertTrue(any(c['target'] == 'test@' + hostname and c['item'] == 'perftest'
                                and c['passed'] for c in report['checks']))
        self.assertTrue(any(c['target'] == 'test@sw1' and c['item'] == 'bf_kdrv'
                            and c['passed'] for c in report['checks']))
        self.assertEqual(sum(c['item'] == 'port-inventory' for c in report['checks']), 4)
        self.assertFalse(any('apt-get' in command or 'modprobe' in command
                             or 'mkdir' in command for _, command in self.commands))

    def test_unreachable_host_skipped_without_blocking_others(self):
        self.offline = {'dc21'}
        with self.assertRaises(CheckFailed):
            self.env.check(self.hosts, {})
        checks = self.env.report['checks']
        self.assertEqual(sum(host == 'dc21' for host, _ in self.commands), 1)
        self.assertTrue(any(c['target'] == 'test@dc21' and c['item'] == 'packages'
                            and c['status'] == 'skipped' and c['passed'] is None for c in checks))
        self.assertTrue(any(c['target'] == 'test@dc23' and c['item'] == 'packages'
                            and c['passed'] for c in checks))

    def test_invalid_agent_records_skips_without_remote_access(self):
        self.agent.side_effect = RuntimeError('Wrong identity')
        with self.assertRaises(CheckFailed):
            self.env.check(self.hosts, {'sw1': {}})
        self.assertEqual(self.commands, [])
        self.assertEqual(self.env.report['summary']['failed'], 1)
        self.assertGreater(self.env.report['summary']['skipped'], 0)

    def test_switch_is_not_an_experiment_data_store(self):
        # The mocked df returns only 1000 KiB. A switch-only preparation must
        # neither create the RDMA data root nor enforce its 10 GiB reserve.
        self.env.config['minimum_free_kib'] = 10485760
        with redirect_stdout(io.StringIO()):
            report = self.env.check({}, {'sw1': {}}, prepare=True)
        self.assertEqual(report['summary']['failed'], 0)
        self.assertFalse(any(c['item'] == 'storage' for c in report['checks']))
        self.assertFalse(any('artifact' in command or command.startswith('df ')
                             for _, command in self.commands))

    def test_rdma_endpoints_still_check_measurement_storage(self):
        self.env.config['minimum_free_kib'] = 10485760
        with redirect_stdout(io.StringIO()), self.assertRaises(CheckFailed):
            self.env.check(self.hosts, {'sw1': {}})
        failed = {(c['target'], c['item']) for c in self.env.report['checks'] if c['status'] == 'failed'}
        self.assertEqual(failed, {('test@' + h, 'storage') for h in ('dc20', 'dc21', 'dc22', 'dc23')})

    def test_success_report(self):
        with redirect_stdout(io.StringIO()) as output:
            report = self.env.check(self.hosts, {})
        self.assertEqual(report['summary']['failed'], 0)
        self.assertEqual(report['summary']['skipped'], 0)
        self.assertIn('RUN test@dc20 packages', output.getvalue())
        self.assertIn('PASS test@dc20 packages', output.getvalue())
        self.assertIn('Environment complete:', output.getvalue())
        self.assertTrue(report['deferred_checks'])
        self.assertIsNone(report['current'])

    def test_prepare_still_stops_on_failure(self):
        self.offline = {'dc20'}
        with self.assertRaisesRegex(RuntimeError, 'Connection unavailable'):
            self.env.check(self.hosts, {}, prepare=True)
        self.assertFalse(any(host == 'dc21' for host, _ in self.commands))
