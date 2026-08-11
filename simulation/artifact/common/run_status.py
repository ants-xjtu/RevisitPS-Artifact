#!/usr/bin/env python3

from __future__ import annotations

import argparse
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
        succeeded = (
            summary["completed"] == summary["expected"]
            and summary["failed"] == 0
            and summary["running"] == 0
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain artifact run status")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--section", required=True)
    init.add_argument("--workload", required=True)
    init.add_argument("--expected", type=int, required=True)
    init.set_defaults(function=command_init)

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
