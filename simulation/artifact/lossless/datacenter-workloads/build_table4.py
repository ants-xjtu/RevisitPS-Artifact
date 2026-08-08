#!/usr/bin/env python3
"""Convert parse_dcn_spine_qlen.py JSON into paper Table 4."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ORDER = ["ECMP", "ConWeave", "DRILL", "RPS", "AR"]


def table_rows(payload: dict) -> list[dict[str, float | str]]:
    by_scheme = {}
    for series in payload.get("data_series", []):
        summary = (series.get("egress_data") or {}).get("summary") or {}
        if "avg_qlen_bytes" not in summary:
            continue
        avg_bytes = float(summary["avg_qlen_bytes"])
        scheme = series["load_balancing_mode"]
        by_scheme[scheme] = {
            "scheme": scheme,
            "avg_egress_qlen_bytes": avg_bytes,
            "avg_egress_qlen_kb": avg_bytes / 1024.0,
        }
    missing = [scheme for scheme in ORDER if scheme not in by_scheme]
    if missing:
        raise ValueError("missing Table 4 schemes: " + ", ".join(missing))
    return [by_scheme[scheme] for scheme in ORDER]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    rows = table_rows(json.loads(args.input_json.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with (args.output_dir / "table4.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "scheme": row["scheme"],
                    "avg_egress_qlen_bytes": (
                        f'{row["avg_egress_qlen_bytes"]:.6f}'
                    ),
                    "avg_egress_qlen_kb": (
                        f'{row["avg_egress_qlen_kb"]:.6f}'
                    ),
                }
            )

    lines = [
        "| Scheme | Average egress queue length (KB) |",
        "|---|---:|",
    ]
    lines.extend(
        f'| {row["scheme"]} | {row["avg_egress_qlen_kb"]:.2f} |'
        for row in rows
    )
    (args.output_dir / "table4.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
