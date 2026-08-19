#!/usr/bin/env python3

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_rto_fct.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_dcn_rto_fct", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotDcnRtoFctTest(unittest.TestCase):
    def test_asymmetric_p99_axes_match_figure14_panels(self):
        module = load_module()

        self.assertEqual(
            module.asymmetric_p99_axis_options("topo_AsymFail1pct_OS1"),
            (5, 90, [5, 20, 40, 60, 90]),
        )
        self.assertEqual(
            module.asymmetric_p99_axis_options("topo_AsymFail10pct_OS1"),
            (5, 200, [5, 50, 100, 150, 200]),
        )
        self.assertEqual(
            module.asymmetric_p99_axis_options("topo_AsymBw10pct_R0.5_OS1"),
            (5, 300, [5, 100, 200, 300]),
        )
        self.assertEqual(
            module.asymmetric_p99_axis_options("topo_AsymBw20pct_R0.5_OS1"),
            (5, 1100, [5, 50, 100, 250, 500, 750, 1100]),
        )
        self.assertEqual(
            module.asymmetric_legend_options("topo_AsymFail10pct_OS1"),
            (None, None),
        )
        self.assertEqual(
            module.asymmetric_legend_options("topo_AsymBw10pct_R0.5_OS1"),
            (2, 3),
        )


if __name__ == "__main__":
    unittest.main()
