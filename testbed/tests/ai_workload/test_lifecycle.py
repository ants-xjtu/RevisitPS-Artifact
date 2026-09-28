import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from framework import runner
from framework.config import load_deployment
from experiments.ai_workload.scripts import run


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {'ARTIFACT_LOCK_DIR': str(self.folder / 'locks')}))
        self.deployment = load_deployment('deployment/deployment.yaml')
        self.spec = run.specifications(SimpleNamespace(workload='alltoall', network_mode='lossless'), self.deployment)[0]
        self.stack.enter_context(patch.object(runner, 'ROOT', self.folder))
        self.stack.enter_context(patch('framework.config.load_deployment', return_value=self.deployment))
        self.stack.enter_context(patch.object(run, 'specifications', return_value=[self.spec]))
        self.stack.enter_context(patch.object(run, 'identity', return_value='same-source'))
        self.stack.enter_context(patch.object(runner, 'perftest_commit', return_value='pinned'))
        self.stack.enter_context(patch('framework.environment.check_agent'))
        self.stack.enter_context(patch.object(run, 'validate_resume_environment'))
        self.recovery = self.stack.enter_context(patch.object(runner, 'recover_processes'))
        self.args = SimpleNamespace(run_id='trial', stage='run', dry_run=False, deployment='site.yaml',
                                    workload='alltoall', network_mode='lossless', repeat=1, resume=False,
                                    refresh_environment=False)
        self.run_dir = self.folder / 'results/ai_workload/trial'

    def fake_task(self, spec, deployment, task, run_dir, state, built, **kwargs):
        folder = run_dir / 'tasks' / task['task_id']
        attempt = folder / f'attempt-{len(list(folder.glob("attempt-*"))) + 1:03d}'
        attempt.mkdir(parents=True)
        path = attempt / 'result.csv'; path.write_text('valid')
        task.update(status='completed', exit_code=0, attempt=str(attempt.relative_to(run_dir)),
                    files={'result.csv': runner.digest(path)})

    def state(self):
        return json.loads((self.run_dir / 'status.json').read_text())

    def test_existing_run_requires_resume_and_verified_completion_is_reused(self):
        with patch.object(run, 'run_task', side_effect=self.fake_task) as execute:
            runner.run_ai(self.args)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                runner.run_ai(self.args)
            self.args.resume = True
            runner.run_ai(self.args)
        self.assertEqual(execute.call_count, 1)
        self.recovery.assert_called_once()

    def test_corrupt_result_or_changed_implementation_blocks_resume_before_cleanup(self):
        with patch.object(run, 'run_task', side_effect=self.fake_task):
            runner.run_ai(self.args)
        self.args.resume = True
        with patch.object(run, 'identity', return_value='changed-source'):
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                runner.run_ai(self.args)
        task = next(iter(self.state()['tasks'].values()))
        (self.run_dir / task['attempt'] / 'result.csv').write_text('truncated')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            runner.run_ai(self.args)
        self.recovery.assert_not_called()

    def test_failed_task_is_persisted_and_retry_uses_new_attempt(self):
        def fail(*args, **kwargs):
            self.fake_task(*args, **kwargs)
            raise TimeoutError('injected timeout')
        with patch.object(run, 'run_task', side_effect=fail):
            with self.assertRaises(TimeoutError):
                runner.run_ai(self.args)
        self.assertEqual(next(iter(self.state()['tasks'].values()))['status'], 'failed')
        self.args.resume = True
        with patch.object(run, 'run_task', side_effect=self.fake_task):
            runner.run_ai(self.args)
        task = next(iter(self.state()['tasks'].values()))
        self.assertTrue(task['attempt'].endswith('attempt-002'))
        self.assertEqual(task['status'], 'completed')

    def test_shared_device_lock_blocks_both_experiments(self):
        with runner.device_lock():
            with self.assertRaisesRegex(RuntimeError, 'already held'):
                with runner.device_lock():
                    self.fail('lock was not exclusive')

    def test_status_is_offline_and_does_not_read_deployment_or_mpi(self):
        self.args.stage = 'status'
        with patch('framework.config.load_deployment', side_effect=AssertionError('deployment')), \
             patch('subprocess.run', side_effect=AssertionError('external process')):
            runner.run_ai(self.args)
