#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
STATUS_TOOL = ARTIFACT_DIR / "common" / "run_status.py"
TRACKING_TOOL = ARTIFACT_DIR / "common" / "run_tracking.sh"


class RunStatusTest(unittest.TestCase):
    def run_tool(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(STATUS_TOOL), *args],
            check=check,
            text=True,
            capture_output=True,
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
