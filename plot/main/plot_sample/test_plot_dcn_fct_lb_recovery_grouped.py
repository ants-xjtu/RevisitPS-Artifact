#!/usr/bin/python3

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("plot_dcn_fct_lb_recovery_grouped.py")


def load_module():
    spec = importlib.util.spec_from_file_location("plot_dcn_fct_lb_recovery_grouped", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotDcnFctLbRecoveryGroupedTest(unittest.TestCase):
    def test_build_plot_groups_combines_100g_and_400g_under_one_family(self):
        module = load_module()
        payload = {
            "variants": [
                {
                    "buffer_size": "0.31",
                    "source_file": "fat_k8_100G_OS1__Lossless__bufsz_0.31.json",
                    "data_series": [
                        {
                            "buffer_size": "0.31",
                            "avg_fct_slowdown": [1.0, 2.0],
                            "p99_fct_slowdown": [3.0, 4.0],
                            "flow_size_buckets_bytes": [100, 200],
                        }
                    ],
                },
                {
                    "buffer_size": "0.31",
                    "source_file": "fat_k8_400G_OS1__Lossless__bufsz_0.31.json",
                    "data_series": [
                        {
                            "buffer_size": "0.31",
                            "avg_fct_slowdown": [5.0, 6.0],
                            "p99_fct_slowdown": [7.0, 8.0],
                            "flow_size_buckets_bytes": [100, 200],
                        }
                    ],
                },
            ]
        }

        groups = module.build_plot_groups(payload)

        self.assertEqual(list(groups.keys()), ["fat_k8__Lossless"])
        self.assertEqual(
            [line["label"] for line in groups["fat_k8__Lossless"]["lines"]],
            ["100G buf=0.31", "400G buf=0.31"],
        )

    def test_build_plot_groups_keeps_single_bandwidth_grouping_and_buffer_labels(self):
        module = load_module()
        payload = {
            "group": {
                "load_balancing_mode": "ECMP",
                "recovery_mechanism": "NAK+GBN",
            },
            "variants": [
                {
                    "buffer_size": "0.31",
                    "source_file": "fat_k8_100G_OS1__Lossless__bufsz_0.31.json",
                    "metadata": {"topology": "fat_k8_100G_OS1"},
                    "data_series": [
                        {
                            "avg_fct_slowdown": [1.0, 2.0],
                            "p99_fct_slowdown": [3.0, 4.0],
                            "flow_size_buckets_bytes": [100, 200],
                            "buffer_size": "0.31",
                        }
                    ],
                },
                {
                    "buffer_size": "0.50",
                    "source_file": "fat_k8_100G_OS1__Lossless__bufsz_0.50.json",
                    "metadata": {"topology": "fat_k8_100G_OS1"},
                    "data_series": [
                        {
                            "avg_fct_slowdown": [5.0, 6.0],
                            "p99_fct_slowdown": [7.0, 8.0],
                            "flow_size_buckets_bytes": [100, 200],
                            "buffer_size": "0.50",
                        }
                    ],
                },
                {
                    "buffer_size": "0.31",
                    "source_file": "leaf_spine_L8_S16_400G_OS1__Lossy__bufsz_0.31.json",
                    "metadata": {"topology": "leaf_spine_L8_S16_400G_OS1"},
                    "data_series": [
                        {
                            "avg_fct_slowdown": [9.0, 10.0],
                            "p99_fct_slowdown": [11.0, 12.0],
                            "flow_size_buckets_bytes": [100, 200],
                            "buffer_size": "0.31",
                        }
                    ],
                },
            ],
        }

        groups = module.build_plot_groups(payload)

        self.assertEqual(set(groups.keys()), {
            "fat_k8_100G_OS1__Lossless",
            "leaf_spine_L8_S16_400G_OS1__Lossy",
        })
        fat_lines = groups["fat_k8_100G_OS1__Lossless"]["lines"]
        self.assertEqual([line["label"] for line in fat_lines], ["buf=0.31", "buf=0.50"])
        self.assertEqual(fat_lines[0]["avg"], [1.0, 2.0])
        self.assertEqual(fat_lines[1]["p99"], [7.0, 8.0])

    def test_draw_json_file_creates_avg_and_p99_pdfs(self):
        module = load_module()
        payload = {
            "group": {
                "load_balancing_mode": "ECMP",
                "recovery_mechanism": "NAK+GBN",
            },
            "variants": [
                {
                    "buffer_size": "0.31",
                    "source_file": "fat_k8_100G_OS1__Lossless__bufsz_0.31.json",
                    "metadata": {"topology": "fat_k8_100G_OS1"},
                    "data_series": [
                        {
                            "avg_fct_slowdown": [1.0, 2.0],
                            "p99_fct_slowdown": [3.0, 4.0],
                            "flow_size_buckets_bytes": [100, 200],
                            "buffer_size": "0.31",
                        }
                    ],
                },
                {
                    "buffer_size": "0.50",
                    "source_file": "fat_k8_100G_OS1__Lossless__bufsz_0.50.json",
                    "metadata": {"topology": "fat_k8_100G_OS1"},
                    "data_series": [
                        {
                            "avg_fct_slowdown": [5.0, 6.0],
                            "p99_fct_slowdown": [7.0, 8.0],
                            "flow_size_buckets_bytes": [100, 200],
                            "buffer_size": "0.50",
                        }
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            json_path = tmpdir / "ECMP__NAK_GBN.json"
            output_dir = tmpdir / "plots"
            json_path.write_text(json.dumps(payload, indent=2) + "\n")

            module.draw_json_file(json_path, output_dir)

            self.assertTrue((output_dir / "ECMP__NAK_GBN__fat_k8_100G_OS1__Lossless_avg.pdf").exists())
            self.assertTrue((output_dir / "ECMP__NAK_GBN__fat_k8_100G_OS1__Lossless_p99.pdf").exists())


if __name__ == "__main__":
    unittest.main()
