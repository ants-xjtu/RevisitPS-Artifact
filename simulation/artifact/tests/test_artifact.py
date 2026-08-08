#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
NS3_ROOT = ARTIFACT_DIR.parent
LOSSLESS_DCN_DIR = ARTIFACT_DIR / "lossless" / "datacenter-workloads"


class ManifestTest(unittest.TestCase):
    def test_paper_experiment_groups_are_explicit(self) -> None:
        script = (LOSSLESS_DCN_DIR / "run_experiments.sh").read_text(
            encoding="utf-8"
        )
        expected_calls = (
            'run_experiment_group "leaf_spine_128_100G_OS2"    "80" "0.000" "AliStorage2019" "dcqcn"  1   0   noar   0       104000  4000 4000 0      fecmp conweave',
            'run_experiment_group "leaf_spine_128_100G_OS2"    "80" "0.000" "AliStorage2019" "dcqcn"  1   0   ar     0       104000  4000 4000 0      drill rps adaptive',
            'run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "AliStorage2019" "dcqcn"  1   0   noar   0       156000  4000 4000 0      fecmp conweave',
            'run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "AliStorage2019" "dcqcn"  1   0   ar     0       156000  4000 4000 0      drill rps adaptive',
            'run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "Solar2022"      "dcqcn"  1   0   noar   0       156000  4000 4000 0      fecmp conweave',
            'run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "Solar2022"      "dcqcn"  1   0   ar     0       156000  4000 4000 0      drill rps adaptive',
            'run_experiment_group "leaf_spine_L8_S16_100G_OS1" "80" "0.000" "FbHdp2015"      "dcqcn"  1   0   noar   0       104000  4000 4000 0      fecmp conweave',
            'run_experiment_group "leaf_spine_L8_S16_100G_OS1" "80" "0.000" "FbHdp2015"      "dcqcn"  1   0   ar     0       104000  4000 4000 0      drill rps adaptive',
        )
        for call in expected_calls:
            self.assertIn(call, script)

    def test_plot_dry_run_uses_three_existing_targets(self) -> None:
        result = subprocess.run(
            [
                str(
                    ARTIFACT_DIR / "lossless" / "datacenter-workloads"
                    / "plot_results.sh"
                ),
                "--dry-run",
            ],
            cwd=NS3_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        commands = [
            line for line in result.stdout.splitlines()
            if line.startswith("PLOT_COMMAND ")
        ]
        self.assertEqual(len(commands), 3)
        self.assertIn("//main/plot_sample:plot_dcn_fct", commands[0])
        self.assertIn("//main/plot_sample:plot_dcn_ooo", commands[1])
        self.assertIn("//main/plot_sample:plot_dcn_pfc_trigger", commands[2])


class ParserPipelineTest(unittest.TestCase):
    def test_parse_dry_run_lists_figure_specific_parsers(self) -> None:
        result = subprocess.run(
            [str(LOSSLESS_DCN_DIR / "parse_results.sh"), "--dry-run"],
            cwd=NS3_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        commands = [
            line for line in result.stdout.splitlines()
            if line.startswith("PARSER_COMMAND ")
        ]
        self.assertEqual(len(commands), 5)
        joined = "\n".join(commands)
        for parser_name in (
            "parse_dcn_fct_rto.py",
            "parse_dcn_ooo.py",
            "parse_dcn_pfc_trigger.py",
            "parse_dcn_spine_qlen.py",
            "build_table4.py",
        ):
            self.assertIn(parser_name, joined)

    def test_table4_is_built_from_spine_parser_json(self) -> None:
        payload = {
            "data_series": [
                {
                    "load_balancing_mode": algorithm,
                    "egress_data": {
                        "summary": {"avg_qlen_bytes": (index + 1) * 1024}
                    },
                }
                for index, algorithm in enumerate(
                    ["ECMP", "ConWeave", "DRILL", "RPS", "AR"]
                )
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            input_json = Path(temp_dir) / "qlen.json"
            output = Path(temp_dir) / "table"
            input_json.write_text(json.dumps(payload), encoding="utf-8")
            subprocess.run(
                [
                    "python3", str(LOSSLESS_DCN_DIR / "build_table4.py"),
                    str(input_json), str(output),
                ],
                check=True,
            )
            with (output / "table4.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(
            [row["scheme"] for row in rows],
            ["ECMP", "ConWeave", "DRILL", "RPS", "AR"],
        )
        self.assertEqual(
            [float(row["avg_egress_qlen_kb"]) for row in rows],
            [1, 2, 3, 4, 5],
        )


if __name__ == "__main__":
    unittest.main()
