import sys
from pathlib import Path
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from experiments.dcn_workload.scripts.parse import parse_fct
from experiments.dcn_workload.scripts.plot_throughput import window_average, aggregate_windows, read_intervals


class AnalysisTests(unittest.TestCase):
    def test_fct_last_row_and_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.csv'
            path.write_text('size,start_time,end_time\n10,100,120\n20,110,140\n30,120,0\n40,180,179\n50,200,230\n')
            rows, counts = parse_fct(path, [10, 20, 30, 40, 50])
            self.assertEqual([(r['size'], r['fct'], r['flow_id']) for r in rows], [(10, 20, 0), (20, 30, 1), (50, 30, 4)])
            self.assertEqual(counts['incomplete'], 1)
            self.assertEqual(counts['nonpositive'], 1)

    def test_truncation_is_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.csv'
            path.write_text('size,start_time,end_time\n10,1,3\n')
            _, counts = parse_fct(path, [10, 20])
            self.assertEqual(counts['incomplete'], 1)

    def test_weighted_window_and_boundary(self):
        rows = [{'start': 0, 'end': 8, 'gbps': 80}, {'start': 8, 'end': 15, 'gbps': 100}]
        self.assertEqual(window_average(rows, 5, 15), 94)
        for rate, passed in [(89, False), (90, True)]:
            self.assertEqual(window_average([{'start': 0, 'end': 15, 'gbps': rate}], 5, 15) >= 90, passed)

    def test_missing_coverage_fails(self):
        with self.assertRaises(ValueError):
            window_average([{'start': 0, 'end': 10, 'gbps': 100}], 5, 15)

    def test_time_alignment_not_line_alignment(self):
        a = [{'start': 0, 'end': 2, 'gbps': 10}, {'start': 2, 'end': 4, 'gbps': 20}]
        b = [{'start': 0, 'end': 1, 'gbps': 1}, {'start': 1, 'end': 4, 'gbps': 3}]
        self.assertEqual([r['gbps'] for r in aggregate_windows([a, b], 0, 4)], [11, 13, 23, 23])

    def test_wrong_bandwidth_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bw.log'
            path.write_text('#bytes iterations BW_peak BW_average\n65535 100 99 90\n')
            with self.assertRaises(ValueError):
                read_intervals(path)
