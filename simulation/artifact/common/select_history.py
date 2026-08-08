#!/usr/bin/env python3
"""Select artifact history rows using the rich experiment manifest."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def split_filter(values: list[str]) -> set[str]:
    return {item for value in values for item in value.split(";") if item}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("history", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--figure", action="append", default=[])
    parser.add_argument("--recipe", action="append", default=[])
    parser.add_argument("--topology", action="append", default=[])
    parser.add_argument("--workload", action="append", default=[])
    parser.add_argument("--group-size", action="append", default=[])
    parser.add_argument("--algorithm", action="append", default=[])
    args = parser.parse_args()

    filters = {
        "recipe": split_filter(args.recipe),
        "topology": split_filter(args.topology),
        "workload": split_filter(args.workload),
        "group_size": split_filter(args.group_size),
        "algorithm": split_filter(args.algorithm),
    }
    figure_filter = split_filter(args.figure)
    with args.manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    wanted = []
    for row in rows:
        if figure_filter and not figure_filter.intersection(row["paper_outputs"].split(";")):
            continue
        if any(values and row[field] not in values for field, values in filters.items()):
            continue
        wanted.append(row["config_id"])
    if not wanted:
        parser.error("selection matched no runs")

    history_by_id = {}
    for line in args.history.read_text(encoding="utf-8").splitlines():
        fields = line.split(",")
        if len(fields) > 1:
            history_by_id[fields[1]] = line
    missing = [config_id for config_id in wanted if config_id not in history_by_id]
    if missing:
        parser.error("manifest IDs missing from history: " + ", ".join(missing))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(history_by_id[config_id] + "\n" for config_id in wanted),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
