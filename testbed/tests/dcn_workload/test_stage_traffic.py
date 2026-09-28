"""Diagnostic traffic is exclusive to check, including resumed runs."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.runner import run_task, check_experiment_traffic


class StageTrafficTests(unittest.TestCase):
    def test_formal_run_and_resume_do_not_send_diagnostics(self):
        for resume in (False, True):
            with self.subTest(resume=resume), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                (root / 'environment.json').write_text('{}')
                stack.enter_context(patch.dict(os.environ))
                stack.enter_context(patch('framework.runner.snapshot', return_value=({}, {}, {}, [])))
                parser = Mock()
                parser.get.return_value.applications.remote_rdma.test.cmd.timeout = 180
                stack.enter_context(patch('framework.runner.prepare_runtime', return_value=parser))
                stack.enter_context(patch('framework.runner.Environment'))
                stack.enter_context(patch('framework.environment_cache.prepare_environment', return_value={}))
                stack.enter_context(patch('switches.scripts.config_sw.run_switch_config'))
                stack.enter_context(patch('framework.rdma.run_test.load_endpoints', return_value=({}, [], {})))
                stack.enter_context(patch('framework.rdma.config_nic.configure'))
                bandwidth = stack.enter_context(patch('framework.rdma.check_link.check_links', side_effect=AssertionError('diagnostic BW in run')))
                smoke = stack.enter_context(patch('framework.rdma.check_link.verify_trace_support', side_effect=AssertionError('smoke in run')))
                execute = stack.enter_context(patch('framework.rdma.run_test.execute_connections'))
                stack.enter_context(patch('framework.runner.trace_inputs', return_value={}))
                stack.enter_context(patch('framework.runner.save_runtime'))
                stack.enter_context(patch('framework.runner.collect_and_validate', return_value={}))
                stack.enter_context(patch('framework.runner.intact', return_value=True))
                task = {'task_id': 'lossless-rps-r001', 'status': 'completed' if resume else 'pending'}
                run_task({'group': 'lossless', 'traffic': 'trace'}, {}, 1, task, root, resume=resume)
                bandwidth.assert_not_called()
                smoke.assert_not_called()
                self.assertEqual(execute.call_count, 0 if resume else 1)
                self.assertEqual(task['status'], 'completed')

    def test_check_deploys_before_bidirectional_and_smoke_tests(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            env = Mock(path=root / 'environment.json', report={})
            env.path.write_text('{}')
            env.record.side_effect = lambda target, item, action: action()
            events = []
            stack.enter_context(patch('framework.runner.snapshot', return_value=({}, {}, {}, [])))
            stack.enter_context(patch('framework.runner.prepare_runtime', return_value=Mock()))
            stack.enter_context(patch('switches.scripts.config_sw.run_switch_config', side_effect=lambda *a, **k: events.append('deploy')))
            stack.enter_context(patch('framework.rdma.run_test.load_endpoints', return_value=({}, [], {})))
            stack.enter_context(patch('framework.rdma.config_nic.configure', side_effect=lambda *a: events.append('nic')))
            stack.enter_context(patch('framework.rdma.check_link.check_links', side_effect=lambda *a: events.append('bandwidth')))
            stack.enter_context(patch('framework.rdma.check_link.verify_trace_support', side_effect=lambda *a: events.append('smoke')))
            before = dict(os.environ)
            check_experiment_traffic({'id': 'lossless-rps', 'group': 'lossless'}, {}, root, env, set())
            self.assertEqual(events, ['deploy', 'nic', 'bandwidth', 'smoke'])
            self.assertEqual(dict(os.environ), before)
