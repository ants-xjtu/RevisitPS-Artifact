#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from artifact_common import (
    add_common_args,
    copy_one,
    resolve_run_paths,
    select_asymmetric_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "tbl08_asym_spine_link_utilization"
SOURCE = (
    "SPINE_DL_UTIL_TOPO_leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1_"
    "LOAD_80_FC_Lossy_TYPE_FbHdp2015_ERR_0.0.json"
)
SCHEMES = ["RPS", "AR", "DRILL", "SGLB"]
SOURCE_ALGORITHMS = {"RPS", "AR", "DRILL", "DRILLGroup", "SGLB"}
FLOWGEN_START_MS = 2000.01
FLOWGEN_END_MS = 2050


def build_table(source: Path, output_dir: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, float | str]] = {}
    for series in payload.get("data_series", []):
        scheme = series["load_balancing_mode"]
        if scheme == "DRILLGroup":
            scheme = "DRILL"
        utilization = series.get("spine_downlink_utilization") or {}
        leaf_balance = utilization.get("leaf_balance_uniformity") or []
        cov_values = [float(item["cv"]) for item in leaf_balance]
        if not cov_values:
            continue
        rows[scheme] = {
            "scheme": scheme,
            "avg_utilization_percent": float(
                utilization["summary"]["avg_util_percent"]
            ),
            "avg_cov": sum(cov_values) / len(cov_values),
            "min_cov": min(cov_values),
            "max_cov": max(cov_values),
            "config_id": series["config_id"],
        }

    missing = [scheme for scheme in SCHEMES if scheme not in rows]
    unexpected = sorted(set(rows) - set(SCHEMES))
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise SystemExit("ERROR: Table 8 schemes: " + "; ".join(details))

    ordered = [rows[scheme] for scheme in SCHEMES]
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / f"{OUTPUT}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "scheme", "avg_utilization_percent", "avg_cov",
            "min_cov", "max_cov", "config_id",
        ])
        writer.writeheader()
        for row in ordered:
            writer.writerow({
                "scheme": row["scheme"],
                "avg_utilization_percent": (
                    f'{row["avg_utilization_percent"]:.6f}'
                ),
                "avg_cov": f'{row["avg_cov"]:.6f}',
                "min_cov": f'{row["min_cov"]:.6f}',
                "max_cov": f'{row["max_cov"]:.6f}',
                "config_id": row["config_id"],
            })

    markdown = [
        "| Scheme | Avg. utilization | Avg. CoV | CoV range |",
        "|---|---:|---:|---:|",
    ]
    for row in ordered:
        markdown.append(
            f'| {row["scheme"]} | '
            f'{row["avg_utilization_percent"]:.2f}% | '
            f'{row["avg_cov"]:.3f} | '
            f'[{row["min_cov"]:.3f}, {row["max_cov"]:.3f}] |'
        )
    (output_dir / f"{OUTPUT}.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse Table 8 asymmetric spine-link utilization."
    )
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("tbl08-history", dry_run=args.dry_run) as work:
        selected = work / "table8.history"
        select_asymmetric_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            recipes={"f14_packet_s3"},
            algorithms=SOURCE_ALGORITHMS,
            expected=4,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_spine_dl_util.py",
            [
                selected,
                "--start-ms", FLOWGEN_START_MS,
                "--end-ms", FLOWGEN_END_MS,
            ],
            dry_run=args.dry_run,
        ) as stage:
            destination = paths.output_dir / f"{OUTPUT}.json"
            copy_one(
                stage / "parser" / "json-data-spine-dl-util" / SOURCE,
                destination,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                print("TABLE_COMMAND build_table8", destination, paths.table_dir)
            else:
                build_table(destination, paths.table_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
