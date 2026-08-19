#!/usr/bin/env python3

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_ooo.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_dcn_ooo", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotDcnOooTest(unittest.TestCase):
    def test_packet_spraying_series_follow_paper_line_order(self):
        module = load_module()
        series = [
            {"load_balancing_mode": "SGLB"},
            {"load_balancing_mode": "AR"},
            {"load_balancing_mode": "RPS"},
            {"load_balancing_mode": "DRILL"},
        ]

        ordered = module.order_data_series(series)

        self.assertEqual(
            [item["load_balancing_mode"] for item in ordered],
            ["RPS", "AR", "SGLB", "DRILL"],
        )

    def test_paper_series_keeps_sglb_and_displays_drillgroup_as_drill(self):
        module = load_module()
        series = [
            {"load_balancing_mode": "ECMP", "recovery_mechanism": "RTO+GBN"},
            {"load_balancing_mode": "RPS", "recovery_mechanism": "RTO+GBN"},
            {"load_balancing_mode": "AR", "recovery_mechanism": "RTO+GBN"},
            {"load_balancing_mode": "SGLB", "recovery_mechanism": "RTO+GBN"},
            {"load_balancing_mode": "DRILLGroup", "recovery_mechanism": "RTO+GBN"},
        ]

        prepared = module.prepare_paper_data_series(series)

        self.assertEqual(
            [item["load_balancing_mode"] for item in prepared],
            ["RPS", "AR", "SGLB", "DRILL"],
        )

    def test_reordering_cdf_uses_paper_axis_ranges(self):
        module = load_module()

        self.assertEqual(module.CDF_X_MAX, 1000)
        self.assertEqual(module.CDF_Y_LIMITS, (0.3, 1.02))
        self.assertAlmostEqual(module.CDF_Y_TICKS[0], 0.3)
        self.assertAlmostEqual(module.CDF_Y_TICKS[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
