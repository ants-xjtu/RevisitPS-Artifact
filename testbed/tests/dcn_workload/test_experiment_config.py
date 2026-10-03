"""Paper experiment expansion and effective hardware configuration contracts."""
import contextlib
import io
import json
from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.runner import main, yaml_read, expand_experiments, snapshot, validate
from framework.rdma.config_nic import verify_psn_window
from framework.conf_parser.yaml_parser import SwitchConfParser


class ExperimentConfigTests(unittest.TestCase):
    def test_paper_selection_expands_all_algorithms_without_hardware(self):
        for fabric in ('lossless', 'lossy'):
            with patch('subprocess.run', side_effect=AssertionError('hardware access')), contextlib.redirect_stdout(io.StringIO()) as out:
                main(['--run-id', 'paper-preview', '--experiment', fabric, '--dry-run'])
            tasks = json.loads(out.getvalue())['tasks']
            self.assertEqual([t['task_id'] for t in tasks],
                             [f'{fabric}-{a}-r001' for a in ('bigswitch', 'ecmp', 'rps')])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main(['--run-id', 'paper-preview', '--experiment', 'lossless-incast', '--dry-run'])

    def test_snapshot_uses_variant_registers_and_shared_traffic(self):
        registry = yaml_read(ROOT / 'experiments/dcn_workload/experiment.yaml')['experiments']
        self.assertEqual([e['id'] for e in registry], ['lossless', 'lossy'])
        expected_links = yaml_read(ROOT / 'experiments/dcn_workload/configs/connections/fully_connected.yaml')['connections']
        self.assertTrue(expected_links)
        traces = []
        for spec in expand_experiments(registry, 'all'):
            config, _, _, switches, links = validate(spec)
            traces.append(config['applications']['gen_trace'])
            self.assertEqual(links, expected_links)
            self.assertEqual(config['applications']['remote_rdma']['test']['cmd']['config']['qp'], 1)
            for role in ('sender', 'receiver'):
                self.assertIn('-m 1024', config['applications']['remote_rdma']['test']['cmd'][role])
                self.assertIn('--qp-timeout=' + ('10' if spec['group']=='lossless' else '6'),
                              config['applications']['remote_rdma']['test']['cmd'][role])
            for switch in switches.values():
                self.assertEqual(switch['PFC_ENABLE'], spec['group']=='lossless')
                direction = 'ingress' if spec['group'] == 'lossless' else 'egress'
                alpha = Fraction(1, 4) if spec['group'] == 'lossless' else Fraction(4)
                baf = Fraction(switch[direction + '_dynamic_baf'].removesuffix('%')) / 100
                self.assertEqual(baf / (1 - baf), alpha)
                other = 'egress' if direction == 'ingress' else 'ingress'
                self.assertEqual(switch[other + '_dynamic_baf'], 'DISABLE')
            with tempfile.TemporaryDirectory() as directory:
                runtime, *_ = snapshot(spec, {'measurement': {}, 'rdma': {'user': 'test'},
                                              'tofino': {'user': 'test'}}, 1, Path(directory))
                hosts = yaml_read(runtime['config']['hosts'])['hosts']
                for host in hosts.values():
                    regs = host['mlxreg']['ROCE_ACCL']
                    self.assertEqual(regs['adaptive_routing_forced_en'], int(spec['algorithm']=='RPS'))
                    self.assertEqual(regs['selective_repeat_forced_en'],
                                     int(spec['group']=='lossy' and spec['algorithm']!='RPS'))
                    self.assertEqual(regs['roce_tx_window_en'], 1)
        self.assertTrue(all(trace == traces[0] for trace in traces))
        self.assertEqual((traces[0]['load'], traces[0]['bandwidth'], traces[0]['time']), (.8, '100G', 180))

    def test_buffer_parser_rejects_alpha_percentages_before_deployment(self):
        parser = SwitchConfParser(str(ROOT / 'switches/configs/bigswitch_lossless.yaml'))
        parser.load_conf_file()
        for field in ('ingress_dynamic_baf', 'egress_dynamic_baf'):
            original = parser.switches['tf_sw2'][field]
            for value in ('25%', '400%', '100%', '0%', '20'):
                with self.subTest(field=field, value=value):
                    parser.switches['tf_sw2'][field] = value
                    with self.assertRaisesRegex(ValueError, field + '.*supported BFRT'):
                        parser.parse_buffer_config('tf_sw2')
            for value in ('DISABLE', '1.5%', '3%', '6%', '11%', '20%', '33%', '50%', '66%', '80%'):
                with self.subTest(field=field, value=value):
                    parser.switches['tf_sw2'][field] = value
                    self.assertEqual(parser.parse_buffer_config('tf_sw2')[field], value)
            parser.switches['tf_sw2'][field] = original

    def test_psn_requires_current_value_not_next_boot(self):
        helper = Mock(ip='test', bus_info='0000:01:00.0')
        for text, passes in [
            ('Configurations: Default Current Next Boot\n LOG_TX_PSN_WINDOW 9 7 7', True),
            ('Configurations: Default Current Next Boot\n LOG_TX_PSN_WINDOW 9 9 7', False),
            ('Configurations: Next Boot\n LOG_TX_PSN_WINDOW 7', False),
        ]:
            helper.ssh.return_value = SimpleNamespace(stdout=text)
            if passes:
                verify_psn_window(helper, 128)
            else:
                with self.assertRaises(RuntimeError):
                    verify_psn_window(helper, 128)
