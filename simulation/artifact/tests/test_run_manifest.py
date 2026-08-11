#!/usr/bin/env python3

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parents[1]
MANIFEST_TOOL = ARTIFACT_DIR / "common" / "run_manifest.py"
TRACKING_TOOL = ARTIFACT_DIR / "common" / "run_tracking.sh"


class RunManifestTest(unittest.TestCase):
    def test_shell_command_passes_metadata_to_runtime_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history = root / "history" / "all.history"
            manifest = root / "manifest.csv"
            script = r'''
source "$1"
artifact_result_files_init "$2" "$3"
artifact_run_command "$3" task-a f4a_base \
    'figure4;figure5;figure6;table4' leaf_spine_128_100G_OS2 \
    AliStorage2019 1 ECMP 0 \
    python3 -c 'from artifact.common.run_manifest import append_runtime_manifest; append_runtime_manifest("123")' &
task_pid=$!
wait "$task_pid"
'''
            result = subprocess.run(
                [
                    "bash", "-c", script, "bash", str(TRACKING_TOOL),
                    str(history), str(manifest),
                ],
                cwd=ARTIFACT_DIR.parent,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with manifest.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["config_id"], "123")
            self.assertEqual(
                rows[0]["paper_outputs"],
                "figure4;figure5;figure6;table4",
            )

    def test_concurrent_runtime_rows_keep_paper_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "manifest.csv"
            subprocess.run(
                ["python3", str(MANIFEST_TOOL), "init", str(manifest)],
                check=True,
            )

            processes = []
            for index in range(16):
                environment = os.environ.copy()
                environment.update({
                    "ARTIFACT_MANIFEST_FILE": str(manifest),
                    "ARTIFACT_TASK_ID": f"task-{index}",
                    "ARTIFACT_RECIPE": "f4a_base",
                    "ARTIFACT_PAPER_OUTPUTS": "figure4;figure5;figure6;table4",
                    "ARTIFACT_TOPOLOGY": "leaf_spine_128_100G_OS2",
                    "ARTIFACT_WORKLOAD": "AliStorage2019",
                    "ARTIFACT_GROUP_SIZE": "1",
                    "ARTIFACT_ALGORITHM": "ECMP",
                    "ARTIFACT_TIMEOUT_MODE": "0",
                    "ARTIFACT_COMMAND": "python3 run.py --lb fecmp",
                })
                processes.append(
                    subprocess.Popen(
                        [
                            "python3", str(MANIFEST_TOOL), "append",
                            str(index + 1000),
                        ],
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )

            for process in processes:
                _, stderr = process.communicate()
                self.assertEqual(process.returncode, 0, stderr)

            with manifest.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 16)
            self.assertEqual(
                {row["paper_outputs"] for row in rows},
                {"figure4;figure5;figure6;table4"},
            )
            self.assertEqual(
                {row["config_id"] for row in rows},
                {str(index + 1000) for index in range(16)},
            )

    def test_retry_replaces_manifest_row_for_the_same_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "manifest.csv"
            environment = os.environ.copy()
            environment.update({
                "ARTIFACT_MANIFEST_FILE": str(manifest),
                "ARTIFACT_TASK_ID": "task-a",
                "ARTIFACT_RECIPE": "f9_t5_base",
                "ARTIFACT_PAPER_OUTPUTS": "figure9;table5",
                "ARTIFACT_TOPOLOGY": "leaf_spine_L8_S16_100G_OS1",
                "ARTIFACT_WORKLOAD": "AliStorage2019",
                "ARTIFACT_GROUP_SIZE": "1",
                "ARTIFACT_ALGORITHM": "ConWeave",
                "ARTIFACT_TIMEOUT_MODE": "0",
                "ARTIFACT_COMMAND": "python3 run.py --lb conweave",
            })

            for config_id in ("100", "200"):
                subprocess.run(
                    ["python3", str(MANIFEST_TOOL), "append", config_id],
                    env=environment,
                    check=True,
                )

            with manifest.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_id"], "task-a")
            self.assertEqual(rows[0]["config_id"], "200")


if __name__ == "__main__":
    unittest.main()
