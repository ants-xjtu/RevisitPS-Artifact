import json
from pathlib import Path
import tempfile
import unittest

from experiments.ai_workload.scripts.plot import collect, plot_results


class SummaryPlotTests(unittest.TestCase):
    def fixture(self, root):
        tasks, rows = {}, []
        for fabric, size in [('lossless', 150 * 1024**2), ('lossy', 75 * 1024**2)]:
            for repeat, means in [(1, [20000, 18000]), (2, [19000, 21000])]:
                key = f'{fabric}-{repeat}'
                attempt = root / key
                (attempt / 'configs').mkdir(parents=True)
                (attempt / 'configs/ai.json').write_text(json.dumps({'parameters': {'target_recv_bytes': size}}))
                tasks[key] = dict(status='completed', attempt=key)
                for group, mean in zip(['nic02', 'nic13'], means):
                    rows.append(dict(task_id=key, network_mode=fabric, workload='alltoall',
                                     algorithm='ECMP', group=group, repeat=repeat, mean_us=mean))
        (root / 'status.json').write_text(json.dumps({'tasks': tasks}))
        (root / 'parsed').mkdir()
        (root / 'parsed/jct.json').write_text(json.dumps(rows))

    def test_minimum_mean_and_actual_capacity_per_fabric(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            points = {p['network_mode']: p for p in collect(root)}
            self.assertEqual(points['lossless']['group'], 'nic13')
            self.assertEqual(points['lossless']['repeat'], 1)
            self.assertEqual(points['lossless']['mean_us'], 18000)
            self.assertAlmostEqual(points['lossless']['ideal_cct_us'], 12839.70612244898)
            self.assertAlmostEqual(points['lossy']['normalized_cct'], 2 * points['lossless']['normalized_cct'])
            plot_results(root)
            for fabric in points:
                for suffix in ('png', 'pdf', 'svg'):
                    self.assertGreater((root / f'figures/cct-{fabric}.{suffix}').stat().st_size, 100)

    def test_mixed_sizes_are_not_silently_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'lossless-2/configs/ai.json').write_text(json.dumps({'parameters': {'target_recv_bytes': 100}}))
            with self.assertRaisesRegex(ValueError, 'Mixed byte budgets'):
                collect(root)
