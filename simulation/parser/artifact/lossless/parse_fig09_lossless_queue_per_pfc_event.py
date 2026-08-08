#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_one, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 9 lossless queue per PFC event JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(
        args.manifest,
        args.history,
        args.selected_history,
        figures={"figure9"},
        workloads={"AlltoallV"},
        group_sizes={"128"},
        expected=5,
    )
    stage_parser(args.ns3_root, args.stage_dir, "parse_dcn_pfc_incast.py", [args.selected_history], dry_run=args.dry_run)
    src = next((args.stage_dir / "parser" / "json-data-pfc-incast-workload").glob("PFC_INCAST_DATA_*.json"), None)
    if src is None and not args.dry_run:
        raise SystemExit("ERROR: no Figure 9 PFC incast JSON produced")
    if src is not None:
        copy_one(src, args.output_dir / "fig09_lossless_queue_per_pfc_event.json", dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
