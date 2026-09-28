"""Only senders emit trace CSVs for the one-way WRITE workload."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.rdma.run_test import execute_connections


class TrafficCollectionTests(unittest.TestCase):
    def run_collection(self, folder, missing=None):
        conf = SimpleNamespace(local_log=str(folder), remote_log='/remote', remote_trace_dir='/trace',
                               cmd=SimpleNamespace(base_port=20000, timeout=10),
                               get=lambda key: '/trace' if key == 'remote_trace_dir' else None)
        parser = Mock()
        parser.get.return_value.applications.remote_rdma.get.return_value = conf
        helpers, copied, commands = {}, [], []
        for ip in ('sender', 'receiver'):
            helper = Mock(target=ip, processes=[])
            helper.absolute.side_effect = lambda path: path
            helper.ssh.return_value = SimpleNamespace(stdout='')
            helper.exit_code.return_value = 0
            helper.get_counter.return_value = 'counters'

            def start(command, log, helper=helper):
                commands.append(command)
                proc = dict(command=command, log=log, state=log, token=log, started=1)
                helper.processes.append(proc)
                return proc

            def copy(source, target):
                copied.append(Path(target).name)
                if source.endswith('.receiver.log.csv') or (missing and source.endswith(missing)):
                    raise FileNotFoundError(source)
                Path(target).write_text('collected')

            helper.start.side_effect = start
            helper.sync_remote_to_local.side_effect = copy
            helpers[ip] = helper
        with patch.dict(os.environ, {'ARTIFACT_SWITCH_LOG': ''}), \
             patch('framework.rdma.run_test.render_command', return_value='ib_write_trace'):
            execute_connections(parser, [{'sender': 'sender', 'receiver': 'receiver'}], helpers)
        return copied, commands

    def test_receiver_csv_is_not_requested_and_sender_csv_is_collected(self):
        with tempfile.TemporaryDirectory() as folder:
            copied, commands = self.run_collection(Path(folder))
            self.assertCountEqual(copied, ['sender-receiver.sender.log',
                'sender-receiver.receiver.log', 'sender-receiver.sender.log.csv'])
            self.assertNotIn('--trace_log', commands[0])
            self.assertIn('--trace_log', commands[1])
            self.assertEqual(json.loads((Path(folder) / 'execution.json').read_text())['errors'], [])

    def test_missing_required_data_still_fails(self):
        for missing in ('.sender.log.csv', '.receiver.log', '.sender.log'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(RuntimeError, 'sender-receiver' + missing.replace('.', r'\.')):
                    self.run_collection(Path(folder), missing)
                self.assertTrue(json.loads((Path(folder) / 'execution.json').read_text())['errors'])
