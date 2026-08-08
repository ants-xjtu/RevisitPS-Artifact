#!/usr/bin/env python3
"""Create paper Table 5 CSV/Markdown from spine-balance parser JSON."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ORDER = ["ECMP", "ConWeave", "DRILL", "RPS", "AR"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    files = sorted(args.input_dir.glob("PFC_SPINE_BALANCE_*.json"))
    if len(files) != 1:
        parser.error(f"expected one Table 5 JSON in {args.input_dir}, found {len(files)}")
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    by_scheme = {}
    for series in payload["data_series"]:
        result = series.get("spine_to_leaf_balance")
        if not result:
            continue
        summary = result["overall_summary"]
        by_scheme[series["load_balancing_mode"]] = {
            "scheme": series["load_balancing_mode"],
            "avg_pause_ms": float(summary["mean_of_means_ns"]) / 1_000_000.0,
            "avg_cov": float(summary["mean_cv"]),
            "min_cov": float(summary["min_cv"]),
            "max_cov": float(summary["max_cv"]),
        }
    missing = [scheme for scheme in ORDER if scheme not in by_scheme]
    if missing:
        parser.error("missing Table 5 schemes: " + ", ".join(missing))
    rows = [by_scheme[scheme] for scheme in ORDER]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "table5.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "scheme": row["scheme"],
                "avg_pause_ms": f'{row["avg_pause_ms"]:.6f}',
                "avg_cov": f'{row["avg_cov"]:.6f}',
                "min_cov": f'{row["min_cov"]:.6f}',
                "max_cov": f'{row["max_cov"]:.6f}',
            })
    lines = [
        "| Scheme | Avg. pause (ms) | Avg. CoV | CoV range |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f'| {row["scheme"]} | {row["avg_pause_ms"]:.2f} | '
            f'{row["avg_cov"]:.3f} | [{row["min_cov"]:.3f}, {row["max_cov"]:.3f}] |'
        )
    (args.output_dir / "table5.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
