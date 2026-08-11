#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from artifact_common import (
    add_common_args,
    copy_one,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "fig08_lossless_pfc_incast_degree"
ITEMS = [
    ("hadoop", "FbHdp2015", "1", "leaf_spine_L8_S16_100G_OS1", "80"),
    ("rpc", "Solar2022", "1", "leaf_spine_L8_S16_100G_OS1", "80"),
    ("storage", "AliStorage2019", "1", "leaf_spine_L8_S16_100G_OS1", "80"),
    ("a2av8", "AlltoallV", "8", "leaf_spine_L8_S16_400G_OS1", "157286400"),
    ("a2av32", "AlltoallV", "32", "leaf_spine_L8_S16_400G_OS1", "157286400"),
    ("a2av128", "AlltoallV", "128", "leaf_spine_L8_S16_400G_OS1", "157286400"),
]


def source_name(
    topology: str, load: str, workload: str, group_size: str
) -> str:
    return (
        f"PFC_INCAST_DATA_TOPO_{topology}_LOAD_{load}_FC_Lossless_"
        f"TYPE_{workload}_ERR_0.0_GROUP_{group_size}.json"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 8 lossless PFC incast.")
    add_common_args(parser)
    parser.add_argument("--datacenter-run-dir", required=True, type=Path)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    datacenter_manifest = args.datacenter_run_dir / "manifest.csv"
    datacenter_history = args.datacenter_run_dir / "history" / "all.history"

    with temporary_workdir("fig08-history", dry_run=args.dry_run) as work:
        combined = work / "figure8.history"
        all_rows: list[str] = []
        for label, workload, group_size, _topology, _load in ITEMS:
            manifest = paths.manifest
            history = paths.history
            if workload != "AlltoallV":
                manifest = datacenter_manifest
                history = datacenter_history
            rows = select_manifest_history(
                manifest,
                history,
                work / f"{label}.history",
                figures={"figure8"},
                workloads={workload},
                group_sizes={group_size},
                expected=5 if workload == "AlltoallV" else 1,
                dry_run=args.dry_run,
            )
            all_rows.extend(rows)
        if not args.dry_run:
            combined.write_text(
                "".join(row + "\n" for row in all_rows), encoding="utf-8"
            )

        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_pfc_incast.py",
            [combined, "--group-by-group-size"],
            dry_run=args.dry_run,
        ) as stage:
            source_dir = stage / "parser" / "json-data-pfc-incast-workload"
            for label, workload, group_size, topology, load in ITEMS:
                copy_one(
                    source_dir / source_name(
                        topology, load, workload, group_size
                    ),
                    paths.output_dir / f"{label}_pfc_incast.json",
                    dry_run=args.dry_run,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
