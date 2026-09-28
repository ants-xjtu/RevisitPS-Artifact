import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.runner import atomic_json, intact, main, digest
from framework.remote import RemoteRDMAHelper
from framework.environment import CheckFailed


class ArtifactTests(unittest.TestCase):
    def test_digest_streams_large_files_without_changing_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.log'
            payload = b'log data\n' * 300000 + b'tail'
            path.write_bytes(payload)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-file allocation')):
                self.assertEqual(digest(path), hashlib.sha256(payload).hexdigest())

    def test_dry_run_does_not_touch_hardware(self):
        with patch('framework.runner.Environment.check', side_effect=AssertionError('hardware')), \
             patch('subprocess.run', side_effect=AssertionError('subprocess')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--run-id', 'dry-run-test', '--dry-run', '--repeat', '2'])
        self.assertEqual(len(json.loads(output.getvalue())['tasks']), 12)

    def test_data_corruption_invalidates_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'task/raw.log'
            path.parent.mkdir()
            path.write_text('complete')
            task = {'attempt': 'task', 'files': {'raw.log': digest(path)}}
            self.assertTrue(intact(task, root))
            path.write_text('truncated')
            self.assertFalse(intact(task, root))

    def test_atomic_status_preserves_previous_on_serialization_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            atomic_json(path, {'status': 'completed'})
            with self.assertRaises(TypeError):
                atomic_json(path, {'bad': object()})
            self.assertEqual(json.loads(path.read_text()), {'status': 'completed'})

    def test_cleanup_uses_identity_not_global_name(self):
        remote = RemoteRDMAHelper('test', 'host')
        with patch.object(remote, 'ssh') as ssh:
            remote.stop({'state': '/tmp/owned', 'token': 'token'})
        command = ssh.call_args.args[0]
        self.assertIn('/proc/$pid/stat', command)
        self.assertIn('ARTIFACT_PROCESS_TOKEN=token', command)
        self.assertNotIn('pkill', command)

    def test_invalid_id_does_not_create_paths(self):
        with self.assertRaises(SystemExit):
            main(['--run-id', '../outside', '--dry-run'])

    def test_check_aggregates_failed_and_successful_experiments(self):
        deployment = {'measurement': {'threshold_gbps': 90, 'duration_seconds': 10,
                                      'warmup_seconds': 5, 'interval_seconds': 1}}
        registry = [{'id': 'first', 'group': 'test'}, {'id': 'second', 'group': 'test'}]
        visited = []

        def check(environment, hosts, switches):
            experiment = environment.path.parent.name
            visited.append(experiment)
            success = experiment == 'second'
            environment.report['checks'] = [dict(target='test@host', item='packages',
                passed=success, status='passed' if success else 'failed', error='missing' if not success else '')]
            environment.save()
            if not success:
                raise CheckFailed('missing')

        previous = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as folder, \
                 patch('framework.runner.ROOT', Path(folder)), \
                 patch('framework.runner.yaml_read', side_effect=lambda path:
                       {'experiments': registry} if path.name == 'experiment.yaml' else deployment), \
                 patch('framework.runner.validate', return_value=(None, None, {}, {}, None)), \
                 patch('framework.runner.perftest_commit', return_value='test'), \
                 patch('framework.runner.device_lock', return_value=contextlib.nullcontext()), \
                 patch('framework.runner.Environment.check', new=check), \
                 patch('framework.environment_cache.prepare_environment',
                       side_effect=lambda env, hosts, switches, *a, **k: env.check(hosts, switches)), \
                 patch('framework.runner.check_experiment_traffic', return_value=None) as traffic_check, \
                 patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(CheckFailed):
                    main(['--run-id', 'aggregate', '--stage', 'check'])
                report = json.loads((Path(folder) / 'results/dcn_workload/aggregate/environment.json').read_text())
                self.assertEqual(visited, ['first', 'second'])
                self.assertEqual(report['summary'], {'total': 3, 'passed': 2, 'failed': 1, 'skipped': 0})
                self.assertEqual(set(report['experiments']), {'first', 'second'})
                self.assertIn('2 passed, 1 failed', output.getvalue())
                traffic_check.assert_called_once()
                self.assertEqual(traffic_check.call_args.args[0]['id'], 'second')
        finally:
            os.chdir(previous)
