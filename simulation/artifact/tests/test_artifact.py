#!/usr/bin/env python3

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
NS3_ROOT = ARTIFACT_DIR.parent
REPO_ROOT = NS3_ROOT.parent
LOSSLESS_DCN_DIR = ARTIFACT_DIR / "lossless" / "datacenter-workloads"


def load_lossless_artifact_common():
    path = NS3_ROOT / "parser" / "artifact" / "lossless" / "artifact_common.py"
    spec = importlib.util.spec_from_file_location("lossless_artifact_common", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_lossless_plot_common():
    path = REPO_ROOT / "plot" / "main" / "plot_artifact" / "lossless" / "plot_common.py"
    spec = importlib.util.spec_from_file_location("lossless_plot_common", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerSafetyTest(unittest.TestCase):
    def test_temporary_plot_input_does_not_pollute_json_directory(self) -> None:
        plot_common = load_lossless_plot_common()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "json"
            input_dir.mkdir()
            (input_dir / "input.json").write_text("{}\n", encoding="utf-8")

            with plot_common.temporary_input_dir(input_dir, "probe") as staged:
                self.assertTrue((staged / "input.json").is_file())
                (staged / "generated.pdf").write_bytes(b"pdf")
                captured_stage = staged

            self.assertFalse(captured_stage.exists())
            self.assertEqual(
                sorted(path.name for path in input_dir.iterdir()),
                ["input.json"],
            )

    def test_temporary_parser_stage_is_removed_after_use(self) -> None:
        artifact_common = load_lossless_artifact_common()
        with tempfile.TemporaryDirectory() as temp_dir:
            ns3_root = Path(temp_dir) / "simulation"
            parser_dir = ns3_root / "parser"
            parser_dir.mkdir(parents=True)
            artifact_package = ns3_root / "artifact"
            artifact_package.mkdir()
            (artifact_package / "__init__.py").write_text("", encoding="utf-8")
            (artifact_package / "probe.py").write_text("VALUE = 1\n", encoding="utf-8")
            (ns3_root / "run.py").write_text(
                "from artifact.probe import VALUE\n",
                encoding="utf-8",
            )
            (parser_dir / "probe.py").write_text(
                "from run import VALUE\nassert VALUE == 1\n",
                encoding="utf-8",
            )
            for name in ("mix", "config", "analysis"):
                (ns3_root / name).mkdir()

            relative_ns3_root = Path(os.path.relpath(ns3_root, Path.cwd()))
            with artifact_common.temporary_parser_stage(
                relative_ns3_root, "probe.py", []
            ) as stage_dir:
                self.assertTrue((stage_dir / "run.py").is_symlink())
                captured_stage = stage_dir

            self.assertFalse(captured_stage.exists())

    def test_managed_results_do_not_contain_parser_workspaces(self) -> None:
        runner = (ARTIFACT_DIR / "run_artifact.sh").read_text(encoding="utf-8")
        status_helper = (ARTIFACT_DIR / "common" / "run_status.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("parser_stage", runner)
        self.assertNotIn("parser_stage", status_helper)
        self.assertNotIn("selected-history", runner)
        self.assertIn('--run-dir "$dir"', runner)

    def test_artifact_plot_wrappers_use_temporary_workspaces(self) -> None:
        plot_root = REPO_ROOT / "plot" / "main" / "plot_artifact"
        for section in ("lossless", "lossy", "asymmetric"):
            for script in (plot_root / section).glob("plot_fig*.py"):
                text = script.read_text(encoding="utf-8")
                self.assertIn("temporary_", text, script)

    def test_main_does_not_shadow_history_lock_module(self) -> None:
        tree = ast.parse((NS3_ROOT / "run.py").read_text(encoding="utf-8"))
        main = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        local_imports = {
            alias.name
            for node in ast.walk(main)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("fcntl", local_imports)

    def test_lossless_collective_runs_after_datacenter_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_dir = Path(temp_dir) / "simulation" / "artifact"
            artifact_dir.mkdir(parents=True)
            runner = artifact_dir / "run_artifact.sh"
            shutil.copy2(ARTIFACT_DIR / "run_artifact.sh", runner)

            for workload, exit_code in (
                ("datacenter-workloads", 7),
                ("collective-communication-workloads", 0),
            ):
                workload_dir = artifact_dir / "lossless" / workload
                workload_dir.mkdir(parents=True)
                script = workload_dir / "run_experiments.sh"
                script.write_text(
                    "#!/usr/bin/env bash\n"
                    "mkdir -p \"$ARTIFACT_RUN_DIR\"\n"
                    "touch \"$ARTIFACT_RUN_DIR/invoked\"\n"
                    f"exit {exit_code}\n",
                    encoding="utf-8",
                )
                script.chmod(0o755)

            result = subprocess.run(
                [
                    str(runner),
                    "--section", "lossless",
                    "--stage", "run",
                    "--run-id", "failure-test",
                ],
                cwd=artifact_dir.parent,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            for workload in (
                "datacenter-workloads",
                "collective-communication-workloads",
            ):

                marker = artifact_dir / "results" / "lossless" / workload
                self.assertTrue((marker / "runs" / "failure-test" / "invoked").is_file())


class ManifestTest(unittest.TestCase):
    def test_paper_experiment_groups_are_explicit(self) -> None:
        script = (LOSSLESS_DCN_DIR / "run_experiments.sh").read_text(
            encoding="utf-8"
        )
        expected_calls = (
            'run_experiment_group "f4a_base"   "figure4;figure5;figure6;table4" "leaf_spine_128_100G_OS2"    80   "0.000" AliStorage2019 dcqcn 1   0   noar   0       104000 4000 4000 0      fecmp conweave',
            'run_experiment_group "f4a_packet" "figure4;figure5;figure6;table4" "leaf_spine_128_100G_OS2"    80   "0.000" AliStorage2019 dcqcn 1   0   ar     0       104000 4000 4000 0      drill rps adaptive',
            'run_experiment_group "f4b_base"   "figure4" "fat_k8_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 noar 0 156000 4000 4000 0 fecmp conweave',
            'run_experiment_group "f4b_packet" "figure4" "fat_k8_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 ar   0 156000 4000 4000 0 drill rps adaptive',
            'run_experiment_group "f6_rpc_base"   "figure6" "fat_k8_100G_OS1" 80 "0.000" Solar2022 dcqcn 1 0 noar 0 156000 4000 4000 0 fecmp conweave',
            'run_experiment_group "f6_rpc_packet" "figure6" "fat_k8_100G_OS1" 80 "0.000" Solar2022 dcqcn 1 0 ar   0 156000 4000 4000 0 drill rps adaptive',
            'run_experiment_group "f6_hadoop_base"   "figure6" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" FbHdp2015 dcqcn 1 0 noar 0 104000 4000 4000 0 fecmp conweave',
            'run_experiment_group "f6_hadoop_packet" "figure6" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" FbHdp2015 dcqcn 1 0 ar   0 104000 4000 4000 0 drill rps adaptive',
            'run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" FbHdp2015      dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive',
            'run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" Solar2022      dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive',
            'run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" AliStorage2019 dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive',
            'run_experiment_group "f9_t5_base"   "figure9;table5" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 noar 0 104000 4000 4000 0 fecmp conweave',
            'run_experiment_group "f9_t5_packet" "figure9;table5" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 ar   0 104000 4000 4000 0 drill rps adaptive',
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
        self.assertEqual(len(commands), 4)
        self.assertIn("//main/plot_sample:plot_dcn_fct", commands[0])
        self.assertIn("//main/plot_sample:plot_dcn_ooo", commands[1])
        self.assertIn("//main/plot_sample:plot_dcn_pfc_trigger", commands[2])
        self.assertIn("//main/plot_sample:plot_dcn_pfc_incast", commands[3])


class ParserPipelineTest(unittest.TestCase):
    def test_pfc_incast_parser_reads_alltoallv_group_size(self) -> None:
        parser_path = NS3_ROOT / "parser" / "parse_dcn_pfc_incast.py"
        spec = importlib.util.spec_from_file_location("parse_dcn_pfc_incast", parser_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            config_dir = output_dir / "123"
            config_dir.mkdir()
            (config_dir / "123_alltoallv_msg_sizes.txt").write_text(
                "# Group 0: 32 nodes\n1 2 3\n",
                encoding="utf-8",
            )

            self.assertEqual(module.get_group_size("123", output_dir, "AlltoallV"), 32)
            self.assertEqual(module.get_group_size("123", output_dir, "AliStorage2019"), 1)
            self.assertIsNone(module.get_group_size("missing", output_dir, "AlltoallV"))

    def test_datacenter_parsers_select_by_manifest_markers(self) -> None:
        parser_dir = NS3_ROOT / "parser" / "artifact" / "lossless"
        for filename in (
            "parse_fig04_lossless_dcn_p99_fct.py",
            "parse_fig05_lossless_ooo_degree.py",
            "parse_fig06_lossless_pfc_pause_duration.py",
            "parse_fig09_lossless_queue_per_pfc_event.py",
            "parse_tbl04_lossless_avg_egress_queue.py",
            "parse_tbl05_lossless_spine_pause_balance.py",
        ):
            script = (parser_dir / filename).read_text(encoding="utf-8")
            self.assertIn("select_manifest_history", script)
            self.assertNotIn("select_history_rows", script)

    def test_figure8_selects_datacenter_and_collective_histories(self) -> None:
        fields = (
            "task_id", "recipe", "paper_outputs", "config_id", "topology",
            "workload", "group_size", "algorithm", "timeout_mode", "command",
        )
        datacenter_rows = []
        collective_rows = []
        for index, workload in enumerate(
            ("FbHdp2015", "Solar2022", "AliStorage2019"), start=1
        ):
            datacenter_rows.append({
                "task_id": f"dcn-{index}",
                "recipe": "pfc_dcn_workloads",
                "paper_outputs": "figure8",
                "config_id": f"10{index}",
                "topology": "leaf_spine_L8_S16_100G_OS1",
                "workload": workload,
                "group_size": "1",
                "algorithm": "AR",
                "timeout_mode": "0",
                "command": "python3 run.py",
            })
        for group_size in (8, 32, 128):
            for index, algorithm in enumerate(
                ("ECMP", "ConWeave", "DRILL", "RPS", "AR"), start=1
            ):
                collective_rows.append({
                    "task_id": f"a2av-{group_size}-{algorithm}",
                    "recipe": "a2av",
                    "paper_outputs": "figure8",
                    "config_id": f"{group_size}{index:02d}",
                    "topology": "leaf_spine_L8_S16_400G_OS1",
                    "workload": "AlltoallV",
                    "group_size": str(group_size),
                    "algorithm": algorithm,
                    "timeout_mode": "0",
                    "command": "python3 run.py",
                })

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources = {}
            for name, rows in (
                ("datacenter", datacenter_rows),
                ("collective", collective_rows),
            ):
                manifest = root / f"{name}.csv"
                history = root / f"{name}.history"
                with manifest.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                history.write_text(
                    "".join(f"date,{row['config_id']}\n" for row in rows),
                    encoding="utf-8",
                )
                sources[name] = (manifest, history)

            run_dirs = {}
            for name, (manifest, history) in sources.items():
                run_dir = root / name
                (run_dir / "history").mkdir(parents=True)
                shutil.copy2(manifest, run_dir / "manifest.csv")
                shutil.copy2(history, run_dir / "history" / "all.history")
                run_dirs[name] = run_dir

            result = subprocess.run(
                [
                    "python3",
                    str(
                        NS3_ROOT / "parser" / "artifact" / "lossless"
                        / "parse_fig08_lossless_pfc_incast_degree.py"
                    ),
                    "--run-dir", str(run_dirs["collective"]),
                    "--datacenter-run-dir", str(run_dirs["datacenter"]),
                    "--ns3-root", str(NS3_ROOT),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            commands = [
                line for line in result.stdout.splitlines()
                if line.startswith("PARSER_COMMAND ")
            ]
            self.assertEqual(len(commands), 1)
            self.assertIn("--group-by-group-size", commands[0])
            for run_dir in run_dirs.values():
                self.assertEqual(
                    sorted(path.name for path in (run_dir / "history").iterdir()),
                    ["all.history"],
                )

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
        self.assertEqual(len(commands), 6)
        joined = "\n".join(commands)
        for parser_name in (
            "parse_dcn_fct_rto.py",
            "parse_dcn_ooo.py",
            "parse_dcn_pfc_trigger.py",
            "parse_dcn_pfc_incast.py",
            "parse_dcn_spine_qlen.py",
            "parse_dcn_pfc_spine_balance.py",
        ):
            self.assertIn(parser_name, joined)
        table_commands = [
            line for line in result.stdout.splitlines()
            if line.startswith("TABLE_COMMAND ")
        ]
        self.assertEqual(len(table_commands), 2)
        self.assertIn("build_table4", table_commands[0])
        self.assertIn("build_table5", table_commands[1])

    def test_workload_filter_only_invokes_selected_parser_group(self) -> None:
        result = subprocess.run(
            [
                str(ARTIFACT_DIR / "run_artifact.sh"),
                "--section", "lossless",
                "--workload", "collective-communication-workloads",
                "--stage", "parse",
                "--run-id", "filter-test",
                "--dry-run",
            ],
            cwd=NS3_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("fig07_lossless_ai_collective_cct", result.stdout)
        self.assertIn("fig08_lossless_pfc_incast_degree", result.stdout)
        self.assertIn("fig10_lossless_spine_queue_timeseries", result.stdout)
        self.assertNotIn("fig04_lossless_dcn_p99_fct", result.stdout)

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
