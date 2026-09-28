"""Readiness reuse across runs, including pre-cache reports and failed checks."""
import copy
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT)]
from framework.environment import Environment, CheckFailed
from framework.environment_cache import (CHECK_SOURCES, implementation_identity, readiness_identity,
                                        prepare_environment, source_digest)


class EnvironmentCacheTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.results = self.root / 'results/dcn_workload'
        for name in CHECK_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# readiness implementation\n')
        source = self.root / 'experiments/dcn_workload/sources/perftest'
        source.mkdir(parents=True)
        (source / 'source.c').write_text('source')
        self.digest = source_digest(source)
        self.deployment = {
            'ssh': {'expected_fingerprints': ['SHA256:test']},
            'packages': ['rsync'], 'remote_root': 'artifact', 'minimum_free_kib': 10,
            'rdma': {'user': 'test', 'stack': 'existing', 'packages': [], 'mtu': 1024},
            'tofino': {'user': 'test', 'sde_command': 'sde-env', 'device_path': '/dev/bf0'},
            'perftest': {'build_command': 'make', 'remote_path': '~/perftest'},
        }
        self.hosts = {'10.0.0.1': {'hostname': 'dc1', 'eth': 'eth0', 'bus_info': 'pci0',
                                 'mlx_device_name': 'mlx5_0', 'mlxreg': {'mode': 1}}}
        self.switches = {'sw1': {'program': {'name': 'bigswitch'}}}
        self.env = Environment(self.deployment, self.results / 'new/environment.json')
        self.check = Mock(side_effect=AssertionError('full check should not run'))
        self.env.check = self.check
        self.stack.enter_context(patch('framework.environment_cache.ROOT', self.root))
        self.stack.enter_context(patch.dict(os.environ, {'PERFTEST_COMMIT': 'commit'}))
        self.agent = self.stack.enter_context(patch('framework.environment_cache.check_agent', return_value=['SHA256:test']))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def report(self, checked_at=1):
        checks = [('local', 'ssh-agent')]
        for target in ('test@dc1', 'test@sw1'):
            checks.extend((target, item) for item in ('management', 'permissions', 'packages'))
        checks.extend(('test@dc1', item) for item in ('storage', 'rdma-stack', 'tool:ibv_devinfo',
                     'tool:mlxreg', 'tool:mlnx_qos', 'verbs', 'memlock', 'perftest'))
        checks.extend(('test@sw1', item) for item in ('nix', 'sde', 'bf_kdrv'))
        checks.extend(('test@dc1/10.0.0.1', item) for item in ('mapping', 'port-inventory'))
        return {
            'checks': [dict(target=target, item=item, status='passed', passed=True) for target, item in checks],
            'current': None, 'discovered_hosts': copy.deepcopy(self.hosts),
            'perftest': {'test@dc1': {'path': '/home/test/perftest-pinned', 'build': 'make',
                                    'source_sha256': self.digest, 'commit': 'commit'}},
            'readiness_cache': dict(version=1, identity=readiness_identity(self.deployment, self.hosts, self.switches),
                                    implementation=implementation_identity(self.root),
                                    checked_at=checked_at, complete=True),
        }

    def write_report(self, report, name='old'):
        path = self.results / name / 'environment.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report))
        return path

    def reuse(self, **kwargs):
        return prepare_environment(self.env, self.hosts, self.switches, self.results, **kwargs)

    def allow_full_check(self, fail=False):
        def check(hosts, switches, prepare):
            if fail:
                raise CheckFailed('offline')
            report = self.report()
            report['readiness_cache'] = self.env.report['readiness_cache']
            self.env.report = report
            return report
        self.check.side_effect = check

    def test_reuses_report_across_runs_and_keeps_current_nic_parameters(self):
        previous = self.report()
        previous['discovered_hosts']['10.0.0.1']['mlxreg'] = {'mode': 0}
        path = self.write_report(previous)
        report = self.reuse()
        self.check.assert_not_called()
        self.agent.assert_called_once_with(['SHA256:test'])
        self.assertEqual(report['perftest'], previous['perftest'])
        self.assertEqual(report['discovered_hosts']['10.0.0.1']['mlxreg'], {'mode': 1})
        self.assertEqual(report['readiness_cache']['reused_from'], str(path))
        self.assertEqual(report['readiness_cache']['checked_at'], 1)
        self.assertEqual(json.loads(self.env.path.read_text()), report)

    def test_newest_failed_check_prevents_fallback_to_older_success(self):
        self.write_report(self.report(1), 'old')
        failed = self.report(2)
        failed['checks'][-1].update(status='failed', passed=False)
        self.write_report(failed, 'recent')
        self.allow_full_check()
        report = self.reuse()
        self.check.assert_called_once()
        self.assertNotIn('reused_from', report['readiness_cache'])

    def test_incomplete_or_skipped_report_is_not_reused(self):
        for kind in ('missing', 'skipped', 'running'):
            with self.subTest(kind=kind):
                report = self.report(100)
                if kind == 'missing':
                    report['checks'].pop()
                elif kind == 'skipped':
                    report['checks'][-1].update(status='skipped', passed=None)
                else:
                    report['current'] = {'status': 'running'}
                self.write_report(report)
                self.allow_full_check()
                self.check.reset_mock()
                self.reuse()
                self.check.assert_called_once()
                self.env.path.unlink()

    def test_configuration_or_implementation_changes_require_full_check(self):
        self.write_report(self.report())
        for change in ('endpoint', 'switch', 'sde', 'source', 'perftest'):
            with self.subTest(change=change), ExitStack() as stack:
                if change == 'endpoint':
                    stack.enter_context(patch.dict(self.hosts['10.0.0.1'], eth='eth1'))
                elif change == 'switch':
                    stack.enter_context(patch.dict(self.switches, sw2={}))
                elif change == 'sde':
                    stack.enter_context(patch.dict(self.deployment['tofino'], sde_command='different'))
                elif change == 'source':
                    stack.enter_context(patch('framework.environment_cache.implementation_identity', return_value={'different': 'code'}))
                else:
                    stack.enter_context(patch('framework.environment_cache.source_digest', return_value='different'))
                self.allow_full_check()
                self.check.reset_mock()
                self.reuse()
                self.check.assert_called_once()
                self.env.path.unlink()

    def test_explicit_refresh_and_failure_invalidate_previous_report(self):
        self.write_report(self.report())
        self.allow_full_check(fail=True)
        with self.assertRaises(CheckFailed):
            self.reuse(refresh=True)
        self.assertFalse(json.loads(self.env.path.read_text())['readiness_cache']['complete'])
        self.allow_full_check()
        self.check.reset_mock()
        self.reuse()
        self.check.assert_called_once()

    def test_agent_failure_stops_cached_run(self):
        self.write_report(self.report())
        self.agent.side_effect = RuntimeError('agent unavailable')
        with self.assertRaisesRegex(RuntimeError, 'agent unavailable'):
            self.reuse()
        self.check.assert_not_called()

    def test_legacy_attempt_report_is_reusable_from_saved_configuration(self):
        run = self.results / 'legacy'
        attempt = run / 'tasks/task/attempt-001'
        configs = attempt / 'configs'
        configs.mkdir(parents=True)
        for name, data in [('deployment.yaml', self.deployment), ('hosts.yaml', {'hosts': self.hosts}),
                           ('switches.yaml', {'switches': self.switches})]:
            (configs / name).write_text(yaml.safe_dump(data))
        for name in CHECK_SOURCES:
            path = run / 'configs/implementation' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / name).read_bytes())
        report = self.report()
        del report['readiness_cache']
        (attempt / 'environment.json').write_text(json.dumps(report))
        reused = self.reuse()
        self.check.assert_not_called()
        self.assertEqual(reused['readiness_cache']['reused_from'], str(attempt / 'environment.json'))


if __name__ == '__main__':
    unittest.main()
