#!/usr/bin/python3

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_pfc_incast.py")
MONOREPO_ROOT = SCRIPT_PATH.parents[2]


def load_module():
    sys.path.insert(0, str(MONOREPO_ROOT))
    spec = importlib.util.spec_from_file_location("plot_dcn_pfc_incast", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotDcnPfcIncastTest(unittest.TestCase):
    def test_merge_carries_file_metadata_into_each_series(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "a2av32_pfc_incast.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "load_type": "AlltoallV",
                            "topology": "leaf_spine",
                            "flow_control": "Lossless",
                        },
                        "data_series": [
                            {
                                "load_balancing_mode": "AR",
                                "recovery_mechanism": "RTO+GBN",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            merged = module.merge_pfc_json_files([str(path)])

        self.assertEqual(
            merged["data_series"],
            [
                {
                    "load_balancing_mode": "AR",
                    "recovery_mechanism": "RTO+GBN",
                    "workload": "AlltoallV",
                    "groupsize": "32",
                    "topology": "leaf_spine",
                    "flow_control": "Lossless",
                }
            ],
        )

    def test_series_filter_can_select_ar_without_dropping_workloads(self):
        module = load_module()
        series_filter = module.build_series_filter("AR")

        self.assertTrue(
            series_filter(
                {
                    "workload": "AlltoallV",
                    "groupsize": "128",
                    "load_balancing_mode": "AR",
                }
            )
        )
        self.assertTrue(
            series_filter(
                {"workload": "FbHdp2015", "load_balancing_mode": "AR"}
            )
        )
        self.assertFalse(
            series_filter(
                {
                    "workload": "AlltoallV",
                    "groupsize": "128",
                    "load_balancing_mode": "RPS",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
