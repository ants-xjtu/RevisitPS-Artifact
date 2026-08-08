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
