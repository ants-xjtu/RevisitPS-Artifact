"""Synthetic fixtures test the pipeline, never stand in for hardware results."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from framework.runner import parse_results, digest
from experiments.dcn_workload.scripts.fct_statistics import summarize_size_buckets, normalize
from experiments.dcn_workload.scripts.plot import plot_results


def fixture_run(root):
    import yaml
    tasks = {}
    for fabric in ('lossless', 'lossy'):
        for algorithm, factor in [('BigSwitch', 1), ('ECMP', 2), ('RPS', 1.1)]:
            task_id = fabric + '-' + algorithm
            attempt = root / 'tasks' / task_id
            (attempt / 'configs').mkdir(parents=True)
            (attempt / 'raw').mkdir()
            raw = attempt / 'raw/a-b.sender.log.csv'
            rows = ['size,start_time,end_time']
            for index in range(190):
                size = 9000 + index * 100000
                start = 100 + index * 100
                rows.append(f'{size},{start},{start + (10 + index) * factor}')
            raw.write_text('\n'.join(rows) + '\n')
            runtime = {'artifact': {'experiment': {'id': task_id, 'group': fabric,
                       'algorithm': algorithm, 'metric': 'fct'}}}
            config = attempt / 'configs/runtime.yaml'
            config.write_text(yaml.safe_dump(runtime))
            tasks[task_id] = {'task_id': task_id, 'repeat': 1, 'status': 'completed',
                             'attempt': str(attempt.relative_to(root)),
                             'files': {'raw/a-b.sender.log.csv': digest(raw), 'configs/runtime.yaml': digest(config)}}
    (root / 'SYNTHETIC-TEST-ONLY.txt').write_text('Unit-test fixture; not measured hardware results.\n')
    status = {'tasks': tasks}
    (root / 'status.json').write_text(json.dumps(status))
    return status


class FctPlotTests(unittest.TestCase):
    def test_normalize_paired_repeats_before_mean(self):
        rows = []
        for repeat, baseline, multiplier in [(1, 10, 2), (2, 100, 4)]:
            for alg in ('ECMP', 'RPS', 'BigSwitch'):
                records = [dict(size=i+1, source='a', flow_id=i,
                                fct=baseline * (1 if alg=='BigSwitch' else multiplier)) for i in range(190)]
                rows.extend(dict(group='lossless', algorithm=alg, repeat=repeat, **r)
                            for r in summarize_size_buckets(records))
        curves = normalize(rows)
        self.assertTrue(all(r['normalized_p99'] == (1 if r['algorithm']=='BigSwitch' else 3) for r in curves))
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            normalize(rows[:-1])
        rows[-1]['input_identity_sha256'] = 'wrong-input'
        with self.assertRaisesRegex(ValueError, 'Unmatched'):
            normalize(rows)

    def test_size_bucket_membership_independent_of_latency(self):
        rows = [dict(size=1000, source='same-size', flow_id=i, fct=i+1) for i in range(190)]
        a = summarize_size_buckets(rows)
        b = summarize_size_buckets([r | {'fct': 200-r['fct']} for r in reversed(rows)])
        self.assertEqual([r['input_identity_sha256'] for r in a], [r['input_identity_sha256'] for r in b])
        self.assertEqual(sum(r['samples'] for r in a), 190)

    def test_parse_and_plot_original_style(self):
        if os.environ.get('FIGURE2_RENDER_TEST') != '1':
            self.skipTest('Set FIGURE2_RENDER_TEST=1 with LaTeX installed for render integration')
        style_files = [ROOT.parent / 'plot/lib/py/plot' / name for name in ('paper.mplstyle', 'plot.py')]
        before = [digest(p) for p in style_files]
        with tempfile.TemporaryDirectory(prefix='synthetic-figure2-') as directory:
            root = Path(directory)
            parse_results(root, fixture_run(root))
            with contextlib.redirect_stdout(io.StringIO()):
                plot_results(root)
            for stem in ('figure2a-lossless', 'figure2b-lossy', 'figure2'):
                for suffix in ('pdf', 'svg', 'png'):
                    self.assertGreater((root / 'figures' / f'{stem}.{suffix}').stat().st_size, 1000)
            self.assertEqual([digest(p) for p in style_files], before)
