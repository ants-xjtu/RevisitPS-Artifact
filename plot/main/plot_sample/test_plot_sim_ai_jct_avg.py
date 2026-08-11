#!/usr/bin/python3

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_sim_ai_jct_avg.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_sim_ai_jct_avg", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotSimAiJctAvgTest(unittest.TestCase):
    def test_lossless_combined_groups_match_figure7_panels(self):
        module = load_module()

        low_categories, low_name, low_combos = module._get_combined_group_settings(
            "lossless-low-incast"
        )
        high_categories, high_name, high_combos = module._get_combined_group_settings(
            "lossless-high-incast"
        )

        self.assertEqual(low_name, "lossless-low-incast")
        self.assertEqual(low_combos, None)
        self.assertEqual(
            low_categories,
            [
                ("Alltoall", 8, "A2A"),
                ("RingAllreduce", 8, "AllR"),
                ("AlltoallV", 8, "A2Av-8"),
                ("AlltoallV", 16, "A2Av-16"),
            ],
        )
        self.assertEqual(high_name, "lossless-high-incast")
        self.assertEqual(high_combos, None)
        self.assertEqual(
            high_categories,
            [
                ("AlltoallV", 32, "A2Av-32"),
                ("AlltoallV", 64, "A2Av-64"),
                ("AlltoallV", 128, "A2Av-128"),
            ],
        )

        lossy_low, lossy_low_name, lossy_low_combos = (
            module._get_combined_group_settings("lossy-low-incast")
        )
        lossy_high, lossy_high_name, lossy_high_combos = (
            module._get_combined_group_settings("lossy-high-incast")
        )
        self.assertEqual(lossy_low_name, "lossy-low-incast")
        self.assertEqual(lossy_low, low_categories)
        self.assertIsNone(lossy_low_combos)
        self.assertEqual(lossy_high_name, "lossy-high-incast")
        self.assertEqual(lossy_high, high_categories)
        self.assertEqual(
            lossy_high_combos,
            module.COMBINED_GROUP_CATEGORIES["4"],
        )

    def test_combined_series_without_panel_points_is_omitted(self):
        module = load_module()
        workload_data = {
            "AlltoallV": {
                "data_series": [
                    {
                        "congestion_control": "NONE",
                        "load_balancing_mode": "AR",
                        "recovery_mechanism": "RTO+GBN",
                        "timeout_mode": "0",
                        "points": [
                            {
                                "group_size": 8,
                                "jct_us": 10,
                                "ideal_jct_us": 5,
                            }
                        ],
                    }
                ]
            }
        }

        series = module._collect_combined_series(
            workload_data,
            module.COMBINED_GROUP_CATEGORIES["lossless-high-incast"],
            dcqcn_only=False,
            no_trimming=False,
            combo_override=None,
        )

        self.assertEqual(series, {})

    def test_group4_combo_override_orders_ar_before_trim(self):
        module = load_module()

        _, group_name, combo_override = module._get_combined_group_settings("4")

        self.assertEqual(group_name, "4")
        self.assertEqual(
            combo_override,
            [
                ("ECMP", "NAK+SR", "DCQCN"),
                ("ConWeave", "NAK+SR", "DCQCN"),
                ("AR", "RTO+GBN+1/2", "DCQCN"),
                ("AR", "IdealTrimming", "DCQCN"),
                ("AR", "RTO+GBN+1/8", "DCQCN"),
                ("AR", "RTO+GBN+1/32", "DCQCN"),
                ("AR", "RTO+GBN+1/128", "DCQCN"),
            ],
        )

    def test_series_label_formats_group4_ar_variants(self):
        module = load_module()

        self.assertEqual(
            module._series_label("AR", "RTO+GBN+1/2", "DCQCN", show_cc=False, show_recovery=True),
            "AR",
        )
        self.assertEqual(
            module._series_label("AR", "IdealTrimming", "DCQCN", show_cc=False, show_recovery=True),
            "AR(Trim)",
        )
        self.assertEqual(
            module._series_label("AR", "RTO+GBN+1/8", "DCQCN", show_cc=False, show_recovery=True),
            "AR (1/8)",
        )
        self.assertEqual(
            module._series_label("AR", "RTO+GBN+1/32", "DCQCN", show_cc=False, show_recovery=True),
            "AR (1/32)",
        )
        self.assertEqual(
            module._series_label("AR", "RTO+GBN+1/128", "DCQCN", show_cc=False, show_recovery=True),
            "AR (1/128)",
        )


if __name__ == "__main__":
    unittest.main()
