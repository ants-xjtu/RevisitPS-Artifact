#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_one, select_manifest_history, stage_parser

ITEMS = [
    ("hadoop", "FbHdp2015", "1", "hadoop_pfc_incast.json"),
    ("rpc", "Solar2022", "1", "rpc_pfc_incast.json"),
    ("storage", "AliStorage2019", "1", "storage_pfc_incast.json"),
    ("a2av8", "AlltoallV", "8", "a2av8_pfc_incast.json"),
    ("a2av32", "AlltoallV", "32", "a2av32_pfc_incast.json"),
    ("a2av128", "AlltoallV", "128", "a2av128_pfc_incast.json"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 8 lossless PFC incast degree JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    for label, workload, group_size, output_name in ITEMS:
        selected = args.selected_history.parent / f"fig08_{label}.history"
        select_manifest_history(
            args.manifest,
            args.history,
            selected,
            figures={"figure8"},
            workloads={workload},
            group_sizes={group_size},
            expected=5 if workload == "AlltoallV" else 1,
        )
        stage = args.stage_dir / label
        stage_parser(args.ns3_root, stage, "parse_dcn_pfc_incast.py", [selected], dry_run=args.dry_run)
        src = next((stage / "parser" / "json-data-pfc-incast-workload").glob("PFC_INCAST_DATA_*.json"), None)
        if src is None and not args.dry_run:
            raise SystemExit(f"ERROR: no PFC incast JSON produced for {label}")
        if src is not None:
            copy_one(src, args.output_dir / output_name, dry_run=args.dry_run)
    args.selected_history.write_text("# Figure 8 uses per-panel selected histories: fig08_*.history\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
