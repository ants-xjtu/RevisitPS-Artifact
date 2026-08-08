#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, build_table5, copy_matching, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 5 lossless spine pause balance JSON/table.")
    parser.add_argument("--table-dir", required=True, type=str)
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"table5"}, group_sizes={"128"}, expected=5)
    stage_parser(
        args.ns3_root,
        args.stage_dir,
        "parse_dcn_pfc_spine_balance.py",
        [args.selected_history, "--servers-per-leaf", 16],
        dry_run=args.dry_run,
    )
    copy_matching(args.stage_dir / "parser" / "json-data-pfc-spine-balance", "PFC_SPINE_BALANCE_*.json", args.output_dir, expected=1, dry_run=args.dry_run)
    build_table5(args.output_dir, __import__("pathlib").Path(args.table_dir), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
