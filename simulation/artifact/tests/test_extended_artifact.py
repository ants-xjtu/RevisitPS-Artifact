#!/usr/bin/env python3

from __future__ import annotations

import csv
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
NS3_ROOT = ARTIFACT_DIR.parent
REPO_ROOT = NS3_ROOT.parent
COMMON_DIR = ARTIFACT_DIR / "common"
sys.path.insert(0, str(COMMON_DIR))

import run_paper_matrix as extended  # noqa: E402


class ExtendedMatrixTest(unittest.TestCase):
    def test_complete_matrix_and_minimal_shared_selections(self) -> None:
        tasks = extended.load_tasks(set(), set())
        self.assertEqual(len(tasks), 188)
        self.assertEqual(len(extended.load_tasks(set(), {"figure7"})), 47)
        self.assertEqual(len(extended.load_tasks(set(), {"figure10"})), 1)
        self.assertEqual(len(extended.load_tasks(set(), {"figure16"})), 6)
        self.assertEqual(len(extended.load_tasks(set(), {"figure17"})), 48)

    def test_paper_ai_and_lossy_parameters(self) -> None:
        tasks = extended.load_tasks(set(), set())
        ai = [task for task in tasks if task.workload in {"Alltoall", "RingAllreduce", "AlltoallV"}]
        self.assertTrue(ai)
        for task in ai:
            self.assertEqual(task.command[:2], ("python3", "run.py"))
            command = " ".join(task.command)
            bw = task.command[task.command.index("--bw") + 1]
            buffer = task.command[task.command.index("--buffer") + 1]
            window = task.command[task.command.index("--windowSize") + 1]
            if "figure17" in task.figures:
                self.assertEqual(bw, "100")
                self.assertEqual(buffer, "0")
                if task.workload == "RingAllreduce":
                    self.assertEqual(window, "512000")
                else:
                    self.assertEqual(window, "104000")
            else:
                self.assertEqual(bw, "400")
                self.assertEqual(buffer, "0.32")
                if task.workload == "RingAllreduce":
                    self.assertEqual(window, "1024000")
                elif "fat" in task.topology:
                    self.assertEqual(window, "606000")
                else:
                    self.assertEqual(window, "404000")
        lossy = [task for task in tasks if "--pfc" in task.command and task.command[task.command.index("--pfc") + 1] == "0"]
        self.assertTrue(lossy)
        for task in lossy:
            command = " ".join(task.command)
            self.assertIn("--rto_high 320", command)
            self.assertIn("--rto_low 100", command)

    def test_lossless_figure8_ai_groups_match_paper(self) -> None:
        tasks = extended.load_tasks(set(), {"figure8"})
        alltoallv_groups = sorted(
            {task.group_size for task in tasks if task.workload == "AlltoallV"}
        )
        self.assertEqual(alltoallv_groups, [8, 32, 128])

    def test_topology_host_bandwidth_matches_command_bw(self) -> None:
        for task in extended.load_tasks(set(), set()):
            bw = task.command[task.command.index("--bw") + 1]
            config = NS3_ROOT / "config" / f"{task.topology}.txt"
            with config.open(encoding="utf-8") as handle:
                first = handle.readline().split()
                n_host = int(first[0]) - int(first[1])
                n_link = int(first[2])
                speeds = set()
                for index, line in enumerate(handle, start=1):
                    if index > n_link:
                        break
                    fields = line.split()
                    if len(fields) >= 3 and (
                        int(fields[0]) < n_host or int(fields[1]) < n_host
                    ):
                        link_speed = fields[2]
                        speeds.add(
                            link_speed[:-4] if link_speed.endswith("Gbps") else link_speed
                        )
            self.assertEqual(speeds, {bw}, task.topology)

    def test_noar_commands_use_timeout_zero(self) -> None:
        for task in extended.load_tasks(set(), set()):
            armode = task.command[task.command.index("--armode") + 1]
            timeout = task.command[
                task.command.index("--timeout_slowstart_mode") + 1
            ]
            if armode == "noar":
                self.assertEqual(timeout, "0", task.task_id)

    def test_all_paper_outputs_are_present(self) -> None:
        with (COMMON_DIR / "experiments_extended.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            outputs = {
                item
                for row in csv.DictReader(handle)
                for item in row["paper_outputs"].split(";")
            }
        self.assertEqual(
            outputs,
            {
                *(f"figure{i}" for i in range(7, 18)),
                "table5", "table6", "table7", "table8",
            },
        )


class ExtendedDryRunTest(unittest.TestCase):
    def test_dry_run_does_not_create_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            # The temporary cwd demonstrates that dry-run is path-independent;
            # results remain anchored to the script and are not written.
            result = subprocess.run(
                [
                    str(COMMON_DIR / "run_paper_matrix.sh"),
                    "--figure", "figure10", "--dry-run",
                ],
                cwd=temp_dir,
                check=True,
                text=True,
                capture_output=True,
            )
        commands = [line for line in result.stdout.splitlines() if line.startswith("COMMAND ")]
        self.assertEqual(len(commands), 1)
        self.assertIn("--lb adaptive", commands[0])
        self.assertIn("--cc none", commands[0])
        self.assertIn("--netload 22469485", commands[0])

    def test_lossless_figure8_plot_uses_paper_incast_groups(self) -> None:
        result = subprocess.run(
            [
                str(
                    ARTIFACT_DIR / "lossless"
                    / "collective-communication-workloads"
                    / "plot_results.sh"
                ),
                "--dry-run",
            ],
            cwd=NS3_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("a2av8_pfc_incast.json", result.stdout)
        self.assertIn("a2av32_pfc_incast.json", result.stdout)
        self.assertIn("a2av128_pfc_incast.json", result.stdout)
        self.assertNotIn("a2av64_pfc_incast.json", result.stdout)

    def test_group_plot_dry_runs_use_expected_plot_targets(self) -> None:
        groups = {
            ("lossless", "collective-communication-workloads"): 4,
            ("lossy", "datacenter-workloads"): 3,
            ("lossy", "collective-communication-workloads"): 2,
            ("asymmetric", "datacenter-workloads"): 4,
            ("asymmetric", "collective-communication-workloads"): 1,
        }
        commands = []
        for (section, workload), expected in groups.items():
            result = subprocess.run(
                [
                    str(
                        ARTIFACT_DIR / section / workload
                        / "plot_results.sh"
                    ),
                    "--dry-run",
                ],
                cwd=NS3_ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            selected = [
                line for line in result.stdout.splitlines()
                if line.startswith("PLOT_COMMAND ")
            ]
            self.assertEqual(len(selected), expected)
            commands.extend(selected)
        joined = "\n".join(commands)
        for target in (
            "plot_sim_ai_jct_avg", "plot_dcn_pfc_incast",
            "plot_single_spine_qlen", "plot_dcn_rto_fct",
            "plot_dcn_ooo", "plot_dcn_unnecessary_retrans",
            "plot_dcn_rto_fct_trim_vs_rto", "plot_sim_ai_jct_avg_asy",
        ):
            self.assertIn(target, joined)


class ChapterLayoutTest(unittest.TestCase):
    GROUPS = {
        ("lossless", "datacenter-workloads"): 28,
        ("lossless", "collective-communication-workloads"): 47,
        ("lossy", "datacenter-workloads"): 12,
        ("lossy", "collective-communication-workloads"): 47,
        ("asymmetric", "datacenter-workloads"): 26,
        ("asymmetric", "collective-communication-workloads"): 48,
    }

    def test_lossy_datacenter_parser_counts_match_runner_matrix(self) -> None:
        parser_root = NS3_ROOT / "parser" / "artifact" / "lossy"
        figure11 = (
            parser_root / "parse_fig11_lossy_dcn_p99_fct_leafspine.py"
        ).read_text(encoding="utf-8")
        figure12 = (
            parser_root / "parse_fig12_lossy_dcn_p99_fct_fattree.py"
        ).read_text(encoding="utf-8")

        self.assertIn('figures={"figure11"}, expected=5', figure11)
        self.assertIn('figures={"figure12"}, expected=7', figure12)

        table6 = (
            parser_root / "parse_tbl06_lossy_packet_drops.py"
        ).read_text(encoding="utf-8")
        table7 = (
            parser_root / "parse_tbl07_lossy_packet_drops.py"
        ).read_text(encoding="utf-8")
        self.assertIn('expected=3', table6)
        self.assertIn('expected=5', table7)

        table8 = (
            NS3_ROOT / "parser" / "artifact" / "asymmetric"
            / "parse_tbl08_asym_spine_link_utilization.py"
        ).read_text(encoding="utf-8")
        self.assertIn('expected=4', table8)
        self.assertIn('recipes={"f14_packet_s3"}', table8)
        self.assertIn('FLOWGEN_START_MS = 2000.01', table8)
        self.assertIn('FLOWGEN_END_MS = 2050', table8)

    def test_trim_and_asymmetric_drill_variants_are_explicit(self) -> None:
        lossy = (
            ARTIFACT_DIR / "lossy" / "datacenter-workloads"
            / "run_experiments.sh"
        ).read_text(encoding="utf-8")
        trim_lines = [
            shlex.split(line)
            for line in lossy.splitlines()
            if line.startswith('run_experiment_group "f11_ar_trim"')
        ]
        self.assertEqual({line[11] for line in trim_lines}, {"0", "2"})

        for workload in (
            "datacenter-workloads", "collective-communication-workloads"
        ):
            runner = (
                ARTIFACT_DIR / "asymmetric" / workload / "run_experiments.sh"
            ).read_text(encoding="utf-8")
            packet_lines = [
                shlex.split(line)
                for line in runner.splitlines()
                if line.startswith("run_experiment_group ")
                and "_packet" in line
            ]
            self.assertTrue(packet_lines)
            for line in packet_lines:
                topology = line[3]
                if "AsymFail" in topology:
                    self.assertIn("drill", line)
                    self.assertNotIn("drillgroup", line)
                else:
                    self.assertIn("AsymBw", topology)
                    self.assertIn("drillgroup", line)
                    self.assertNotIn("drill", line)

    def test_lossy_figure13_wrapper_generates_both_paper_panels(self) -> None:
        wrapper = (
            REPO_ROOT / "plot" / "main" / "plot_artifact" / "lossy"
            / "plot_fig13_lossy_ai_collective_cct.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"lossy-low-incast"', wrapper)
        self.assertIn('"lossy-high-incast"', wrapper)
        self.assertIn(
            "fig13{panel}_lossy_ai_collective_cct_{suffix}.pdf", wrapper
        )
        self.assertIn('"--raw-ytop"', wrapper)
        self.assertIn('"--raw-ystep"', wrapper)
        self.assertIn('"--legend-loc"', wrapper)

    def test_lossy_figure12_wrapper_generates_two_p99_panels(self) -> None:
        wrapper = (
            REPO_ROOT / "plot" / "main" / "plot_artifact" / "lossy"
            / "plot_fig12_lossy_dcn_p99_fct_fattree.py"
        ).read_text(encoding="utf-8")

        self.assertIn('[staged, "--metric", "p99", *filters]', wrapper)
        self.assertIn("fig12{panel}_lossy_dcn_p99_fct_fattree_{suffix}.pdf", wrapper)
        self.assertIn('"--p99-ymin", "30", "--p99-ymax", "1450"', wrapper)
        self.assertIn('"--p99-ymin", "20", "--p99-ymax", "1450"', wrapper)

    def test_asymmetric_wrappers_name_all_paper_panels(self) -> None:
        wrapper_root = (
            REPO_ROOT / "plot" / "main" / "plot_artifact" / "asymmetric"
        )
        figure14 = (wrapper_root / "plot_fig14_asym_dcn_fct.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '[staged, "--metric", "p99", "--asymmetric-paper-p99-axes"]',
            figure14,
        )
        self.assertIn('("a", "s1", "AsymFail1pct")', figure14)
        self.assertIn('("b", "s2", "AsymFail10pct")', figure14)
        self.assertIn('("c", "s3", "AsymBw10pct_R0.5")', figure14)
        self.assertIn('("d", "s4", "AsymBw20pct_R0.5")', figure14)
        self.assertIn("fig14{panel}_asym_dcn_p99_fct_{scenario}.pdf", figure14)
        self.assertNotIn("copy_matching", figure14)

        figure15 = (wrapper_root / "plot_fig15_asym_ooo_retransmission.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("fig15a_asym_reordering_distance_s3.pdf", figure15)
        self.assertIn("fig15b_asym_retransmission_breakdown.pdf", figure15)

        figure16 = (wrapper_root / "plot_fig16_asym_packet_trim_rto.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("fig16{panel}_asym_packet_trim_rto_{metric}.pdf", figure16)
        self.assertIn(
            '[staged, "--legend-ncol", 2, "--legend-loc", "upper left"]',
            figure16,
        )

        figure17 = (wrapper_root / "plot_fig17_asym_ai_collective_cct.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("fig17{panel}_asym_ai_collective_cct_{suffix}.pdf", figure17)
        self.assertIn("loc=_scenario_legend_location(load_type)", (
            REPO_ROOT / "plot" / "main" / "plot_sample"
            / "plot_sim_ai_jct_avg_asy.py"
        ).read_text(encoding="utf-8"))

    def test_every_group_has_readme_run_and_plot_entry_points(self) -> None:
        for section, workload in self.GROUPS:
            root = ARTIFACT_DIR / section / workload
            for filename in (
                "README.md", "run_experiments.sh", "parse_results.sh",
                "plot_results.sh",
            ):
                self.assertTrue((root / filename).is_file(), root / filename)

    def test_parse_wrappers_call_parser_phase_not_plot_phase(self) -> None:
        for section, workload in self.GROUPS:
            root = ARTIFACT_DIR / section / workload
            parse_text = (root / "parse_results.sh").read_text(
                encoding="utf-8"
            )
            plot_text = (root / "plot_results.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn("--stage parse", parse_text)
            self.assertIn("--stage plot", plot_text)
            self.assertNotIn("--stage plot", parse_text)
            self.assertNotIn("--stage parse", plot_text)

    def test_figure_parsers_have_one_run_directory_interface(self) -> None:
        for section in ("lossless", "lossy", "asymmetric"):
            parser_dir = NS3_ROOT / "parser" / "artifact" / section
            for script in parser_dir.glob("parse_*.py"):
                text = script.read_text(encoding="utf-8")
                self.assertIn("resolve_run_paths", text, script)
                self.assertNotIn("args.stage_dir", text, script)
                self.assertNotIn("args.selected_history", text, script)

    def test_runners_record_figure_metadata_while_run_py_writes_history(self) -> None:
        for section, workload in self.GROUPS:
            script = (
                ARTIFACT_DIR / section / workload / "run_experiments.sh"
            ).read_text(encoding="utf-8")
            self.assertIn("artifact_result_files_init", script)
            self.assertIn("artifact_run_command", script)
            self.assertIn("if artifact_tracking_enabled; then", script)
            self.assertIn("artifact_tracking_init", script)
            self.assertIn("artifact_wait_for_tasks", script)
            self.assertIn("artifact_tracking_finalize", script)
            self.assertNotIn("Config filename:", script)
            self.assertNotIn("history_row=$(awk", script)

        managed_runner = (ARTIFACT_DIR / "run_artifact.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(managed_runner.count("env ARTIFACT_RUN_DIR="), 6)

    def test_lossless_figure8_references_belong_to_datacenter_runner(self) -> None:
        datacenter = (
            ARTIFACT_DIR / "lossless" / "datacenter-workloads"
            / "run_experiments.sh"
        ).read_text(encoding="utf-8")
        collective = (
            ARTIFACT_DIR / "lossless" / "collective-communication-workloads"
            / "run_experiments.sh"
        ).read_text(encoding="utf-8")

        def references(script: str) -> list[list[str]]:
            return [
                shlex.split(line)
                for line in script.splitlines()
                if line.startswith('run_experiment_group "pfc_dcn_workloads"')
            ]

        datacenter_references = references(datacenter)
        self.assertEqual(
            {group[6] for group in datacenter_references},
            {"FbHdp2015", "Solar2022", "AliStorage2019"},
        )
        self.assertEqual(references(collective), [])

    def test_lossless_figure9_and_table5_use_leaf_spine_storage(self) -> None:
        datacenter = (
            ARTIFACT_DIR / "lossless" / "datacenter-workloads"
            / "run_experiments.sh"
        ).read_text(encoding="utf-8")
        collective = (
            ARTIFACT_DIR / "lossless" / "collective-communication-workloads"
            / "run_experiments.sh"
        ).read_text(encoding="utf-8")
        orchestrator = (ARTIFACT_DIR / "run_artifact.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"figure9;table5" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" '
            "AliStorage2019",
            datacenter,
        )
        self.assertNotIn("table5", collective)
        self.assertIn(
            "parse_one lossless datacenter-workloads "
            "parse_fig09_lossless_queue_per_pfc_event.py",
            orchestrator,
        )
        self.assertIn(
            "plot_one lossless datacenter-workloads "
            "plot_fig09_lossless_queue_per_pfc_event.py",
            orchestrator,
        )
        self.assertIn(
            "parse_one lossless datacenter-workloads "
            "parse_tbl05_lossless_spine_pause_balance.py",
            orchestrator,
        )

    def test_explicit_runner_lines_partition_the_complete_artifact(self) -> None:
        parameter_counts = {
            ("lossless", "datacenter-workloads"): 15,
            ("lossless", "collective-communication-workloads"): 18,
            ("lossy", "datacenter-workloads"): 16,
            ("lossy", "collective-communication-workloads"): 18,
            ("asymmetric", "datacenter-workloads"): 16,
            ("asymmetric", "collective-communication-workloads"): 18,
        }
        for (section, workload), expected in self.GROUPS.items():
            runner = (
                ARTIFACT_DIR / section / workload / "run_experiments.sh"
            ).read_text(encoding="utf-8")
            self.assertNotIn("common/run_paper_matrix.sh", runner)
            groups = [
                shlex.split(line)
                for line in runner.splitlines()
                if line.startswith("run_experiment_group ")
            ]
            fixed = 1 + parameter_counts[(section, workload)]
            task_count = sum(len(group) - fixed for group in groups)
            self.assertEqual(task_count, expected)


if __name__ == "__main__":
    unittest.main()
