#!/usr/bin/env python3

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_fct.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_dcn_fct", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotDcnFctTest(unittest.TestCase):
    def test_lossless_series_follow_paper_legend_order(self):
        module = load_module()

        self.assertEqual(
            module.desired_order_for_lossless,
            [
                "ECMP(NAK+GBN)",
                "ConWeave(NAK+GBN)",
                "AR(RTO+GBN)",
                "DRILL(RTO+GBN)",
                "RPS(RTO+GBN)",
            ],
        )


if __name__ == "__main__":
    unittest.main()
