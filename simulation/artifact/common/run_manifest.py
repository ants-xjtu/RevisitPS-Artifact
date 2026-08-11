#!/usr/bin/env python3
"""Write the artifact manifest when run.py records a simulator history row."""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import sys
from pathlib import Path
from typing import Mapping


FIELDS = (
    "task_id",
    "recipe",
    "paper_outputs",
    "config_id",
    "topology",
    "workload",
    "group_size",
    "algorithm",
    "timeout_mode",
    "command",
)

ENV_FIELDS = {
    "task_id": "ARTIFACT_TASK_ID",
    "recipe": "ARTIFACT_RECIPE",
    "paper_outputs": "ARTIFACT_PAPER_OUTPUTS",
    "topology": "ARTIFACT_TOPOLOGY",
    "workload": "ARTIFACT_WORKLOAD",
    "group_size": "ARTIFACT_GROUP_SIZE",
    "algorithm": "ARTIFACT_ALGORITHM",
    "timeout_mode": "ARTIFACT_TIMEOUT_MODE",
    "command": "ARTIFACT_COMMAND",
}


def initialize_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=FIELDS).writeheader()
    path.chmod(0o644)


def append_manifest_row(path: Path, row: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", newline="", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0, os.SEEK_END)
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if handle.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)
    path.chmod(0o644)


def append_runtime_manifest(
    config_id: str, environment: Mapping[str, str] = os.environ
) -> bool:
    manifest_value = environment.get("ARTIFACT_MANIFEST_FILE")
    if not manifest_value:
        return False

    missing = [name for name in ENV_FIELDS.values() if not environment.get(name)]
    if missing:
        raise RuntimeError(
            "artifact manifest metadata is incomplete: " + ", ".join(missing)
        )
    row = {
        field: environment[variable]
        for field, variable in ENV_FIELDS.items()
    }
    row["config_id"] = str(config_id)
    append_manifest_row(Path(manifest_value), row)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("manifest", type=Path)
    append = subparsers.add_parser("append")
    append.add_argument("config_id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "init":
            initialize_manifest(args.manifest)
        else:
            append_runtime_manifest(args.config_id)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
