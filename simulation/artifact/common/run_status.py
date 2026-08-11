#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


TERMINAL_STATES = {"completed", "failed"}


def canonical_task_id(row: dict[str, str]) -> str:
    return (
        f'{row["recipe"]}__{row["topology"]}__{row["workload"]}'
        f'__g{row["group_size"]}__{row["algorithm"]}'
        f'__t{row["timeout_mode"]}'
    )


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def locked(run_dir: Path) -> Iterator[None]:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".status.lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.chmod(0o644)
    os.replace(temporary, path)


def load_state(run_dir: Path) -> dict:
    status_path = run_dir / "status.json"
    if not status_path.is_file():
        raise RuntimeError(f"missing status file: {status_path}")
    with status_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def calculate_summary(state: dict) -> dict[str, int]:
    counts = {"running": 0, "completed": 0, "failed": 0}
    for task in state["tasks"].values():
        task_status = task["status"]
        if task_status in counts:
            counts[task_status] += 1
    accounted = sum(counts.values())
    return {
        "expected": state["expected"],
        "pending": max(state["expected"] - accounted, 0),
        **counts,
    }


def save_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = timestamp()
    state["summary"] = calculate_summary(state)
    atomic_write(
        run_dir / "status.json",
        json.dumps(state, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(run_dir / "status", state["state"] + "\n")


def command_init(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    with locked(run_dir):
        status_path = run_dir / "status.json"
        history_path = run_dir / "history" / "all.history"
        if status_path.exists() or history_path.exists():
            raise RuntimeError(f"run directory already exists: {run_dir}")
        now = timestamp()
        state = {
            "state": "running",
            "section": args.section,
            "workload": args.workload,
            "expected": args.expected,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "tasks": {},
        }
        for directory in ("history", "logs", "json", "figures", "tables"):
            (run_dir / directory).mkdir(parents=True, exist_ok=True)
        save_state(run_dir, state)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    with locked(run_dir):
        state = load_state(run_dir)
        if state["section"] != args.section or state["workload"] != args.workload:
            raise RuntimeError(
                "resume section/workload does not match existing run: "
                f'{state["section"]}/{state["workload"]}'
            )

        manifest_path = run_dir / "manifest.csv"
        history_path = run_dir / "history" / "all.history"
        if not manifest_path.is_file() or not history_path.is_file():
            raise RuntimeError(f"resume metadata is incomplete: {run_dir}")
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle))
        by_config = {row["config_id"]: row for row in manifest_rows}

        normalized_tasks = {}
        for old_task_id, task in state["tasks"].items():
            row = by_config.get(str(task.get("config_id", "")))
            task_id = canonical_task_id(row) if row is not None else old_task_id
            normalized = dict(task)
            normalized["task_id"] = task_id
            previous = normalized_tasks.get(task_id)
            if previous is None or normalized.get("status") == "completed":
                normalized_tasks[task_id] = normalized

        if args.expected < len(normalized_tasks):
            raise RuntimeError(
                f"resume expected count {args.expected} is smaller than "
                f"the {len(normalized_tasks)} recorded tasks"
            )
        state["tasks"] = normalized_tasks
        state["expected"] = args.expected
        state["state"] = "running"
        state["finished_at"] = None
        save_state(run_dir, state)
    return 0


def command_update(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    with locked(run_dir):
        state = load_state(run_dir)
        if state["state"] != "running":
            raise RuntimeError(
                f"cannot update a run in state {state['state']}: {run_dir}"
            )
        task = state["tasks"].setdefault(
            args.task_id,
            {"task_id": args.task_id, "started_at": timestamp()},
        )
        task["status"] = args.status
        task["updated_at"] = timestamp()
        if args.status == "running":
            for field in ("config_id", "exit_code", "finished_at"):
                task.pop(field, None)
        if args.log is not None:
            task["log"] = args.log
        if args.config_id is not None:
            task["config_id"] = args.config_id
        if args.exit_code is not None:
            task["exit_code"] = args.exit_code
        if args.status in TERMINAL_STATES:
            task["finished_at"] = timestamp()
        save_state(run_dir, state)
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    with locked(run_dir):
        state = load_state(run_dir)
        summary = calculate_summary(state)
        if summary["running"] > 0:
            state["state"] = "running"
            state["finished_at"] = None
            save_state(run_dir, state)
            return 1

        succeeded = (
            summary["completed"] == summary["expected"]
            and summary["failed"] == 0
        )
        state["state"] = "completed" if succeeded else "failed"
        state["finished_at"] = timestamp()
        save_state(run_dir, state)
    return 0 if succeeded else 1


def command_check(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    state = load_state(run_dir)
    if state["state"] != "completed":
        raise RuntimeError(f"run is {state['state']}, not completed: {run_dir}")
    return 0


def command_show(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    state = load_state(run_dir)
    summary = calculate_summary(state)
    print(f"run_dir={run_dir}")
    print(f"state={state['state']}")
    for key in ("expected", "pending", "running", "completed", "failed"):
        print(f"{key}={summary[key]}")
    return 0


def command_task_completed(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir.resolve())
    task = state["tasks"].get(args.task_id)
    return 0 if task is not None and task.get("status") == "completed" else 1


def command_task_skippable(args: argparse.Namespace) -> int:
    state = load_state(args.run_dir.resolve())
    task = state["tasks"].get(args.task_id)
    return (
        0
        if task is not None and task.get("status") in {"running", "completed"}
        else 1
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain artifact run status")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--section", required=True)
    init.add_argument("--workload", required=True)
    init.add_argument("--expected", type=int, required=True)
    init.set_defaults(function=command_init)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--run-dir", type=Path, required=True)
    resume.add_argument("--section", required=True)
    resume.add_argument("--workload", required=True)
    resume.add_argument("--expected", type=int, required=True)
    resume.set_defaults(function=command_resume)

    update = subparsers.add_parser("update")
    update.add_argument("--run-dir", type=Path, required=True)
    update.add_argument("--task-id", required=True)
    update.add_argument(
        "--status", choices=("running", "completed", "failed"), required=True
    )
    update.add_argument("--log")
    update.add_argument("--config-id")
    update.add_argument("--exit-code", type=int)
    update.set_defaults(function=command_update)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--run-dir", type=Path, required=True)
    finalize.set_defaults(function=command_finalize)

    check = subparsers.add_parser("check")
    check.add_argument("--run-dir", type=Path, required=True)
    check.set_defaults(function=command_check)

    show = subparsers.add_parser("show")
    show.add_argument("--run-dir", type=Path, required=True)
    show.set_defaults(function=command_show)

    task_completed = subparsers.add_parser("task-completed")
    task_completed.add_argument("--run-dir", type=Path, required=True)
    task_completed.add_argument("--task-id", required=True)
    task_completed.set_defaults(function=command_task_completed)

    task_skippable = subparsers.add_parser("task-skippable")
    task_skippable.add_argument("--run-dir", type=Path, required=True)
    task_skippable.add_argument("--task-id", required=True)
    task_skippable.set_defaults(function=command_task_skippable)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.function(args)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
