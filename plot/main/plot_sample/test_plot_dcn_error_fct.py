#!/usr/bin/python3

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_error_fct.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_dcn_error_fct", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rgba(value):
    return mcolors.to_rgba(value)


class PlotDcnErrorFctTest(unittest.TestCase):
    def test_draw_error_rate_fct_plot_applies_requested_style_to_avg_and_p99(self):
        module = load_module()
        payload = {
            "data_series": [
                {
                    "load_balancing_mode": "AR",
                    "recovery_mechanism": "RTO+GBN",
                    "error_rate": "0.0",
                    "flow_size_buckets_bytes": [1000, 2000, 4000],
                    "avg_fct_slowdown": [1.0, 1.5, 2.0],
                    "p99_fct_slowdown": [2.0, 2.5, 3.0],
                },
                {
                    "load_balancing_mode": "AR",
                    "recovery_mechanism": "RTO+GBN",
                    "error_rate": "0.001",
                    "flow_size_buckets_bytes": [1000, 2000, 4000],
                    "avg_fct_slowdown": [1.1, 1.6, 2.1],
                    "p99_fct_slowdown": [2.1, 2.6, 3.1],
                },
                {
                    "load_balancing_mode": "AR",
                    "recovery_mechanism": "RTO+GBN",
                    "error_rate": "0.0001",
                    "flow_size_buckets_bytes": [1000, 2000, 4000],
                    "avg_fct_slowdown": [1.2, 1.7, 2.2],
                    "p99_fct_slowdown": [2.2, 2.7, 3.2],
                },
            ]
        }

        captured = {}
        original_savefig = module.plt.savefig
        original_close = module.plt.close

        def fake_savefig(path, *args, **kwargs):
            fig = plt.gcf()
            captured[Path(path).name] = fig

        def fake_close(*args, **kwargs):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "sample.json"
            json_path.write_text(json.dumps(payload, indent=2) + "\n")
            module.plt.savefig = fake_savefig
            module.plt.close = fake_close
            try:
                module.draw_error_rate_fct_plot(str(json_path), tmp)
            finally:
                module.plt.savefig = original_savefig
                module.plt.close = original_close

        self.assertEqual(sorted(captured.keys()), ["sample_AR_RTO_GBN__avg.pdf", "sample_AR_RTO_GBN__p99.pdf"])

        for fig in captured.values():
            ax = fig.axes[0]
            legend = ax.get_legend()

            self.assertEqual(tuple(round(v, 1) for v in fig.get_size_inches()), (9.6, 6.0))
            self.assertEqual(ax.get_title(), "")
            self.assertEqual(ax.xaxis.label.get_fontfamily()[0], "DejaVu Sans")
            self.assertEqual(ax.yaxis.label.get_fontfamily()[0], "DejaVu Sans")
            self.assertEqual(ax.xaxis.label.get_size(), 35.0)
            self.assertEqual(ax.yaxis.label.get_size(), 35.0)
            self.assertEqual(ax.xaxis.label.get_color(), "black")
            self.assertEqual(ax.yaxis.label.get_color(), "black")

            for label in ax.get_xticklabels() + ax.get_yticklabels():
                self.assertEqual(label.get_fontfamily()[0], "DejaVu Sans")
                self.assertEqual(label.get_color(), "black")
                self.assertEqual(label.get_size(), 30.0)

            for spine in ax.spines.values():
                self.assertEqual(spine.get_edgecolor(), _rgba("black"))

            for line in ax.xaxis.get_ticklines() + ax.yaxis.get_ticklines():
                self.assertEqual(line.get_color(), "black")

            self.assertIsNotNone(legend)
            self.assertEqual(legend._ncols, 2)
            self.assertEqual(legend._loc, 8)
            anchor = legend.get_bbox_to_anchor()._bbox
            self.assertAlmostEqual(anchor.x0, 0.5)
            self.assertAlmostEqual(anchor.y0, 1.02)
            self.assertEqual(legend.get_frame().get_facecolor(), _rgba("white"))
            self.assertEqual(legend.get_frame().get_edgecolor(), _rgba("dimgray"))
            self.assertEqual(legend.get_frame().get_alpha(), 1.0)
            for text in legend.get_texts():
                self.assertEqual(text.get_fontfamily()[0], "DejaVu Sans")
                self.assertEqual(text.get_size(), 25.0)

        plt.close("all")


if __name__ == "__main__":
    unittest.main()
