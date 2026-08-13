#!/usr/bin/env python3
"""Expand and optionally run the paper Figure 7--17/Table 5--7 recipes."""

from __future__ import annotations

import argparse
import csv
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


COMMON_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = COMMON_DIR.parent
NS3_ROOT = ARTIFACT_DIR.parent
MATRIX = COMMON_DIR / "experiments_extended.csv"
DEFAULT_RESULTS = ARTIFACT_DIR / "results" / "extended"
PROCESS_PATTERN = "build/scratch/network-load-balance"

LB = {
    "ECMP": ("fecmp", "noar"),
    "ConWeave": ("conweave", "noar"),
    "DRILL": ("drill", "ar"),
    "DRILLGroup": ("drillgroup", "ar"),
    "RPS": ("rps", "ar"),
    "AR": ("adaptive", "ar"),
    "SGLB": ("sglb", "ar"),
}


class MatrixError(RuntimeError):
    pass


@dataclass(frozen=True)
class Task:
    recipe: str
    figures: tuple[str, ...]
    topology: str
    workload: str
    group_size: int
    algorithm: str
    timeout_mode: int
    command: tuple[str, ...]

    @property
    def task_id(self) -> str:
        parts = (
            self.recipe, self.topology, self.workload, f"g{self.group_size}",
            self.algorithm, f"t{self.timeout_mode}",
        )
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", "__".join(parts))


def split(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def actual_netload(kind: str, requested: int, workload: str, group_size: int) -> int:
    if kind == "percent":
        return requested
    if kind != "target_recv":
        raise MatrixError(f"unknown netload_kind: {kind}")
    if workload == "Alltoall":
        return requested // (group_size - 1)
    if workload == "RingAllreduce":
        return requested // (2 * (group_size - 1))
    return requested


def load_tasks(recipe_filter: set[str], figure_filter: set[str]) -> list[Task]:
    tasks: list[Task] = []
    seen: dict[tuple[str, ...], Task] = {}
    with MATRIX.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "recipe", "paper_outputs", "topologies", "workloads", "group_sizes",
        "algorithms", "cc", "pfc", "irn", "timeout_mode", "bw", "buffer",
        "netload_kind", "netload", "window_size", "rto_high", "rto_low", "pattern",
    }
    if not rows or set(rows[0]) != required:
        raise MatrixError(f"unexpected columns in {MATRIX}")

    for row in rows:
        figures = tuple(split(row["paper_outputs"]))
        if recipe_filter and row["recipe"] not in recipe_filter:
            continue
        if figure_filter and not figure_filter.intersection(figures):
            continue
        for topology in split(row["topologies"]):
            if not (NS3_ROOT / "config" / f"{topology}.txt").is_file():
                raise MatrixError(f"missing topology config/{topology}.txt")
            for workload in split(row["workloads"]):
                for group_text in split(row["group_sizes"]):
                    group_size = int(group_text)
                    for algorithm in split(row["algorithms"]):
                        if algorithm not in LB:
                            raise MatrixError(f"unknown algorithm {algorithm}")
                        lb, armode = LB[algorithm]
                        for timeout_text in split(row["timeout_mode"]):
                            timeout = int(timeout_text)
                            load = actual_netload(
                                row["netload_kind"], int(row["netload"]),
                                workload, group_size,
                            )
                            command = [
                                "python3", "run.py",
                                "--cc", row["cc"], "--lb", lb,
                                "--pfc", row["pfc"], "--irn", row["irn"],
                                "--armode", armode, "--simul_time", "0.05",
                                "--netload", str(load), "--topo", topology,
                                "--cdf", workload, "--error_rate", "0.0",
                                "--flowgen_mode", "src",
                                "--timeout_slowstart_mode", str(timeout),
                                "--windowSize", row["window_size"],
                                "--rto_high", row["rto_high"],
                                "--rto_low", row["rto_low"],
                                "--buffer", row["buffer"], "--bw", row["bw"],
                            ]
                            if workload in {"Alltoall", "RingAllreduce", "AlltoallV"}:
                                command += ["--ai_nodes_per_group", str(group_size)]
                            if workload == "AlltoallV":
                                command += ["--netload_pattern", row["pattern"]]
                            task = Task(
                                row["recipe"], figures, topology, workload,
                                group_size, algorithm, timeout, tuple(command),
                            )
                            old = seen.get(task.command)
                            if old is not None:
                                raise MatrixError(
                                    f"duplicate command in {old.recipe} and {task.recipe}"
                                )
                            seen[task.command] = task
                            tasks.append(task)
    if not tasks:
        raise MatrixError("selection produced no tasks")
    return tasks


def print_command(task: Task) -> None:
    print(
        "COMMAND",
        f"recipe={task.recipe}",
        f"figures={';'.join(task.figures)}",
        shlex.join(task.command),
    )


def global_process_count() -> int:
    result = subprocess.run(
        ["pgrep", "-fc", "--", PROCESS_PATTERN], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def extract_history(log_path: Path) -> tuple[str, str]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"Config filename:.*/mix/output/([^/]+)/config\.txt", text)
    if not matches:
        raise MatrixError(f"cannot find config ID in {log_path}")
    config_id = matches[-1]
    history = NS3_ROOT / "mix" / ".history"
    for line in history.read_text(encoding="utf-8").splitlines():
        fields = line.split(",")
        if len(fields) > 1 and fields[1] == config_id:
            return config_id, line
    raise MatrixError(f"config ID {config_id} not found in {history}")


def run_tasks(
    tasks: list[Task], jobs: int, force: bool, results: Path
) -> None:
    history_path = results / "extended.history"
    manifest_path = results / "extended_runs.csv"
    logs = results / "logs"
    histories = results / "history"
    protected = [history_path, manifest_path]
    if not force and any(path.exists() for path in protected):
        raise MatrixError(f"{results} already contains a run; use --force")
    logs.mkdir(parents=True, exist_ok=True)
    histories.mkdir(parents=True, exist_ok=True)

    active: list[tuple[Task, Path, object, subprocess.Popen[str]]] = []
    completed: list[tuple[Task, str, str]] = []
    failed = False

    def reap(block: bool) -> None:
        nonlocal active, failed
        while True:
            remaining = []
            changed = False
            for task, log_path, handle, process in active:
                code = process.wait() if block else process.poll()
                if code is None:
                    remaining.append((task, log_path, handle, process))
                    continue
                handle.close()
                changed = True
                if code != 0:
                    print(f"ERROR: {task.task_id} failed; see {log_path}", file=sys.stderr)
                    failed = True
                else:
                    config_id, history_row = extract_history(log_path)
                    completed.append((task, config_id, history_row))
            active = remaining
            if changed or not block or not active:
                return
            time.sleep(1)

    for task in tasks:
        while len(active) >= jobs or global_process_count() >= jobs:
            reap(False)
            if len(active) >= jobs or global_process_count() >= jobs:
                time.sleep(1)
        log_path = logs / f"{task.task_id}.log"
        if log_path.exists() and not force:
            raise MatrixError(f"log exists: {log_path}; use --force")
        handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            task.command, cwd=NS3_ROOT, stdout=handle, stderr=subprocess.STDOUT,
            text=True,
        )
        active.append((task, log_path, handle, process))
        time.sleep(1)
        reap(False)
    while active:
        reap(True)
    if failed:
        raise MatrixError("one or more simulations failed")

    completed.sort(key=lambda item: item[0].task_id)
    history_path.write_text(
        "".join(row + "\n" for _, _, row in completed), encoding="utf-8"
    )
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "task_id", "recipe", "paper_outputs", "config_id", "topology",
            "workload", "group_size", "algorithm", "timeout_mode", "command",
        ])
        for task, config_id, _ in completed:
            writer.writerow([
                task.task_id, task.recipe, ";".join(task.figures), config_id,
                task.topology, task.workload, task.group_size, task.algorithm,
                task.timeout_mode, shlex.join(task.command),
            ])
    all_figures = sorted({figure for task, _, _ in completed for figure in task.figures})
    for figure in all_figures:
        rows = [row for task, _, row in completed if figure in task.figures]
        (histories / f"{figure}.history").write_text(
            "".join(row + "\n" for row in rows), encoding="utf-8"
        )
    print(f"Completed {len(completed)} tasks. Manifest: {manifest_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the extended NSDI paper artifact matrix."
    )
    parser.add_argument("--recipe", action="append", default=[], help="select recipe")
    parser.add_argument(
        "--figure", action="append", default=[],
        help="select figure7..figure17 or table5..table7",
    )
    parser.add_argument("--jobs", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS,
        help="artifact-local directory for logs and run manifests",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        tasks = load_tasks(set(args.recipe), set(args.figure))
        if args.dry_run:
            for task in tasks:
                print_command(task)
            print(f"TOTAL_COMMANDS {len(tasks)}")
        else:
            run_tasks(
                tasks, args.jobs, args.force, args.results_dir.resolve()
            )
    except (MatrixError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
