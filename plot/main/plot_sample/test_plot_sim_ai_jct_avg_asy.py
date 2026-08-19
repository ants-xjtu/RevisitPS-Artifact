#!/usr/bin/env python3

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_sim_ai_jct_avg_asy.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_sim_ai_jct_avg_asy", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotSimAiJctAvgAsymmetricTest(unittest.TestCase):
    def test_figure17a_legend_is_placed_on_the_left(self):
        module = load_module()

        self.assertEqual(module._scenario_legend_location("Alltoall"), "upper left")
        self.assertEqual(module._scenario_legend_location("RingAllreduce"), "best")

    def test_drill_source_follows_asymmetric_scenario(self):
        module = load_module()
        series = [
            {"load_balancing_mode": "DRILL", "value": "drill"},
            {"load_balancing_mode": "DRILLGroup", "value": "drillgroup"},
        ]

        failure = module._apply_scenario_drill_policy({
            "metadata": {"topology": "leafspine_L8_S16_100G_AsymFail1pct_OS1"},
            "data_series": series,
        })
        bandwidth = module._apply_scenario_drill_policy({
            "metadata": {"topology": "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1"},
            "data_series": series,
        })

        self.assertEqual(
            failure["data_series"],
            [{"load_balancing_mode": "DRILL", "value": "drill"}],
        )
        self.assertEqual(
            bandwidth["data_series"],
            [{"load_balancing_mode": "DRILL", "value": "drillgroup"}],
        )


if __name__ == "__main__":
    unittest.main()
