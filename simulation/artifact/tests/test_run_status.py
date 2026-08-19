#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
STATUS_TOOL = ARTIFACT_DIR / "common" / "run_status.py"
TRACKING_TOOL = ARTIFACT_DIR / "common" / "run_tracking.sh"
RUNNER = ARTIFACT_DIR / "run_artifact.sh"
MANIFEST_FIELDS = (
    "task_id", "recipe", "paper_outputs", "config_id", "topology",
    "workload", "group_size", "algorithm", "timeout_mode", "command",
)


class RunStatusTest(unittest.TestCase):
    def run_tool(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(STATUS_TOOL), *args],
            check=check,
            text=True,
            capture_output=True,
        )

    def write_manifest(self, run_dir: Path, **overrides: str) -> str:
        row = {
            "task_id": "legacy-task",
            "recipe": "f9_t5_base",
            "paper_outputs": "figure9;table5",
            "config_id": "101",
            "topology": "leaf_spine_L8_S16_100G_OS1",
            "workload": "AliStorage2019",
            "group_size": "1",
            "algorithm": "ECMP",
            "timeout_mode": "0",
            "command": "python3 run.py",
            **overrides,
        }
        with (run_dir / "manifest.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        return (
            f'{row["recipe"]}__{row["topology"]}__{row["workload"]}'
            f'__g{row["group_size"]}__{row["algorithm"]}'
            f'__t{row["timeout_mode"]}'
        )

    def test_tracks_running_completed_and_failed_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "2",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-a",
                "--status", "running", "--log", "logs/task-a.log",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-a",
                "--status", "completed", "--config-id", "123",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-b",
                "--status", "failed", "--exit-code", "7",
            )
            result = self.run_tool("finalize", "--run-dir", str(run_dir), check=False)

            self.assertNotEqual(result.returncode, 0)
            state = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "failed")
            self.assertEqual(state["summary"], {
                "expected": 2,
                "pending": 0,
                "running": 0,
                "completed": 1,
                "failed": 1,
            })
            self.assertEqual((run_dir / "status").read_text(encoding="utf-8"), "failed\n")

    def test_status_files_remain_host_readable_after_atomic_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "1",
            )

            for filename in ("status", "status.json"):
                self.assertEqual((run_dir / filename).stat().st_mode & 0o777, 0o644)

    def test_reset_tasks_removes_stopped_recipe_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ns3_root = Path(temp_dir) / "simulation"
            run_dir = ns3_root / "artifact" / "results" / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossy",
                "--workload", "datacenter-workloads", "--expected", "2",
            )
            history = run_dir / "history" / "all.history"
            history.write_text("date,101,keep\ndate,202,trim\n", encoding="utf-8")
            shared_history = ns3_root / "mix" / ".history"
            shared_history.parent.mkdir(parents=True)
            shared_history.write_text(
                "date,101,keep\n"
                "/simulator /mix/output/101/config.txt\n"
                "date,202,trim\n"
                "/simulator /mix/output/202/config.txt\n",
                encoding="utf-8",
            )
            output = ns3_root / "mix" / "output" / "202"
            output.mkdir(parents=True)
            (output / "result").write_text("old\n", encoding="utf-8")

            self.write_manifest(run_dir, task_id="task-keep")
            with (run_dir / "manifest.csv").open(
                "a", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
                writer.writerow({
                    "task_id": "task-trim",
                    "recipe": "f11_ar_trim",
                    "paper_outputs": "figure11",
                    "config_id": "202",
                    "topology": "leaf_spine_L8_S16_100G_OS1",
                    "workload": "AliStorage2019",
                    "group_size": "1",
                    "algorithm": "AR",
                    "timeout_mode": "2",
                    "command": "python3 run.py",
                })
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-keep",
                "--status", "completed", "--config-id", "101",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-trim",
                "--status", "failed", "--config-id", "202",
            )

            result = self.run_tool(
                "reset-tasks", "--run-dir", str(run_dir),
                "--recipe", "f11_ar_trim", "--ns3-root", str(ns3_root),
            )

            self.assertIn("reset_tasks=1", result.stdout)
            self.assertEqual(history.read_text(encoding="utf-8"), "date,101,keep\n")
            self.assertEqual(
                shared_history.read_text(encoding="utf-8"),
                "date,101,keep\n/simulator /mix/output/101/config.txt\n",
            )
            self.assertFalse(output.exists())
            with (run_dir / "manifest.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["config_id"] for row in rows], ["101"])
            state = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(set(state["tasks"]), {"task-keep"})
            self.assertEqual(state["state"], "failed")

    def test_reset_tasks_rejects_running_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossy",
                "--workload", "datacenter-workloads", "--expected", "1",
            )
            self.write_manifest(
                run_dir, task_id="task-trim", recipe="f11_ar_trim"
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-trim",
                "--status", "running", "--config-id", "101",
            )

            result = self.run_tool(
                "reset-tasks", "--run-dir", str(run_dir),
                "--recipe", "f11_ar_trim", check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot reset running tasks", result.stderr)
            self.assertIn("f11_ar_trim", (run_dir / "manifest.csv").read_text())

            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "task-a",
                "--status", "running",
            )
            for filename in ("status", "status.json"):
                self.assertEqual((run_dir / filename).stat().st_mode & 0o777, 0o644)

    def test_rejects_reusing_an_existing_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            args = (
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "1",
            )
            self.run_tool(*args)
            second = self.run_tool(*args, check=False)

            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already exists", second.stderr)

    def test_resume_normalizes_legacy_task_ids_and_expands_expected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "1",
            )
            (run_dir / "history" / "all.history").write_text(
                "date,101\n", encoding="utf-8"
            )
            canonical = self.write_manifest(run_dir)
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "legacy-task",
                "--status", "completed", "--config-id", "101",
            )
            self.run_tool("finalize", "--run-dir", str(run_dir))

            self.run_tool(
                "resume", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "2",
            )

            state = json.loads(
                (run_dir / "status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["state"], "running")
            self.assertEqual(state["summary"]["expected"], 2)
            self.assertEqual(state["summary"]["completed"], 1)
            self.assertEqual(state["summary"]["pending"], 1)
            self.assertEqual(set(state["tasks"]), {canonical})
            self.run_tool(
                "task-completed", "--run-dir", str(run_dir),
                "--task-id", canonical,
            )

    def test_resume_active_run_skips_running_and_completed_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "3",
            )
            (run_dir / "history" / "all.history").write_text(
                "date,101\n", encoding="utf-8"
            )
            completed = self.write_manifest(run_dir, task_id="task-completed")
            self.run_tool(
                "update", "--run-dir", str(run_dir),
                "--task-id", "task-completed", "--status", "completed",
                "--config-id", "101",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir),
                "--task-id", "task-running", "--status", "running",
            )
            self.run_tool(
                "update", "--run-dir", str(run_dir),
                "--task-id", "task-failed", "--status", "failed",
                "--exit-code", "1",
            )

            self.run_tool(
                "resume", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "3",
            )

            self.run_tool(
                "task-skippable", "--run-dir", str(run_dir),
                "--task-id", completed,
            )
            self.run_tool(
                "task-skippable", "--run-dir", str(run_dir),
                "--task-id", "task-running",
            )
            failed = self.run_tool(
                "task-skippable", "--run-dir", str(run_dir),
                "--task-id", "task-failed", check=False,
            )
            self.assertNotEqual(failed.returncode, 0)

            finalized = self.run_tool(
                "finalize", "--run-dir", str(run_dir), check=False
            )
            self.assertNotEqual(finalized.returncode, 0)
            state = json.loads(
                (run_dir / "status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["state"], "running")
            self.assertIsNone(state["finished_at"])

    def test_shell_resume_preserves_metadata_and_skips_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "1",
            )
            history = run_dir / "history" / "all.history"
            history.write_text("row-old\n", encoding="utf-8")
            canonical = self.write_manifest(run_dir)
            manifest_before = (run_dir / "manifest.csv").read_bytes()
            self.run_tool(
                "update", "--run-dir", str(run_dir), "--task-id", "legacy-task",
                "--status", "completed", "--config-id", "101",
            )
            self.run_tool("finalize", "--run-dir", str(run_dir))

            script = r'''
source "$1"
artifact_tracking_init lossless datacenter-workloads 2
artifact_result_files_init "$ARTIFACT_RUN_DIR/history/all.history" "$ARTIFACT_RUN_DIR/manifest.csv"
artifact_run_background "$2" "$ARTIFACT_RUN_DIR/logs/skipped.log" bash -c \
    'touch "$ARTIFACT_RUN_DIR/skipped"'
artifact_run_background task-new "$ARTIFACT_RUN_DIR/logs/new.log" bash -c \
    'printf "Config filename:/mix/output/202/config.txt\\n"; printf "row-new\\n" >> "$ARTIFACT_HISTORY_FILE"'
artifact_wait_for_tasks
artifact_tracking_finalize
'''
            environment = os.environ.copy()
            environment["ARTIFACT_RUN_DIR"] = str(run_dir)
            environment["ARTIFACT_RESUME"] = "1"
            result = subprocess.run(
                ["bash", "-c", script, "bash", str(TRACKING_TOOL), canonical],
                env=environment, text=True, capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Skip running/completed task", result.stdout)
            self.assertFalse((run_dir / "skipped").exists())
            self.assertEqual(
                history.read_text(encoding="utf-8").splitlines(),
                ["row-old", "row-new"],
            )
            self.assertEqual((run_dir / "manifest.csv").read_bytes(), manifest_before)
            state = json.loads(
                (run_dir / "status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["state"], "completed")
            self.assertEqual(state["summary"]["completed"], 2)

    def test_managed_runner_forwards_resume_mode(self) -> None:
        result = subprocess.run(
            [
                str(RUNNER), "--section", "lossless", "--workload",
                "datacenter-workloads", "--stage", "run", "--run-id",
                "resume-dry-run", "--resume", "--dry-run",
            ],
            cwd=ARTIFACT_DIR.parent,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("ARTIFACT_RESUME=1", result.stdout)

    def test_shell_tracking_propagates_init_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", "1",
            )
            script = r'''
source "$1"
artifact_tracking_init lossless datacenter-workloads 1
'''
            environment = os.environ.copy()
            environment["ARTIFACT_RUN_DIR"] = str(run_dir)
            result = subprocess.run(
                ["bash", "-c", script, "bash", str(TRACKING_TOOL)],
                env=environment, text=True, capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)

    def test_show_reports_summary_without_modifying_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "collective-communication-workloads",
                "--expected", "50",
            )
            before = (run_dir / "status.json").read_bytes()
            result = self.run_tool("show", "--run-dir", str(run_dir))

            self.assertIn("state=running", result.stdout)
            self.assertIn("expected=50", result.stdout)
            self.assertIn("pending=50", result.stdout)
            self.assertEqual((run_dir / "status.json").read_bytes(), before)

    def test_shell_tracking_records_parallel_task_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            script = r'''
source "$1"
artifact_tracking_init lossless datacenter-workloads 2
artifact_run_background task-a "$ARTIFACT_RUN_DIR/logs/a.log" bash -c \
    'printf "Config filename:/mix/output/101/config.txt\\n"; printf "row-a\\n" >> "$ARTIFACT_HISTORY_FILE"'
artifact_run_background task-b "$ARTIFACT_RUN_DIR/logs/b.log" bash -c \
    'printf "Config filename:/mix/output/202/config.txt\\n"; printf "row-b\\n" >> "$ARTIFACT_HISTORY_FILE"'
artifact_wait_for_tasks
artifact_tracking_finalize
'''
            environment = os.environ.copy()
            environment["ARTIFACT_RUN_DIR"] = str(run_dir)
            result = subprocess.run(
                ["bash", "-c", script, "bash", str(TRACKING_TOOL)],
                env=environment, text=True, capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "completed")
            self.assertEqual(state["summary"]["completed"], 2)
            self.assertEqual(
                set((run_dir / "history" / "all.history").read_text(
                    encoding="utf-8"
                ).splitlines()),
                {"row-a", "row-b"},
            )

    def test_concurrent_updates_do_not_drop_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "trial"
            expected = 16
            self.run_tool(
                "init", "--run-dir", str(run_dir), "--section", "lossless",
                "--workload", "datacenter-workloads", "--expected", str(expected),
            )

            def update_all(status: str) -> None:
                processes = [
                    subprocess.Popen(
                        [
                            "python3", str(STATUS_TOOL), "update",
                            "--run-dir", str(run_dir), "--task-id", f"task-{index}",
                            "--status", status,
                        ],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    for index in range(expected)
                ]
                for process in processes:
                    _, stderr = process.communicate()
                    self.assertEqual(process.returncode, 0, stderr)

            update_all("running")
            self.assertNotEqual(
                self.run_tool("check", "--run-dir", str(run_dir), check=False).returncode,
                0,
            )
            update_all("completed")
            self.run_tool("finalize", "--run-dir", str(run_dir))
            self.run_tool("check", "--run-dir", str(run_dir))

            state = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "completed")
            self.assertEqual(state["summary"]["completed"], expected)



if __name__ == "__main__":
    unittest.main()
