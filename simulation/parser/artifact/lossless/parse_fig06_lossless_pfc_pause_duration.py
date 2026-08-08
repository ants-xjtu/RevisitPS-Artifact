#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_matching, select_history_rows, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 6 lossless PFC pause duration JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    select_history_rows(
        args.history,
        args.selected_history,
        lambda f: (f[15] == "fat_k8_100G_OS1" and f[17] == "Solar2022" and f[18] == "80")
        or (f[15] == "leaf_spine_128_100G_OS2" and f[17] == "AliStorage2019" and f[18] == "80")
        or (f[15] == "leaf_spine_L8_S16_100G_OS1" and f[17] == "FbHdp2015" and f[18] == "80"),
        expected=15,
    )
    stage_parser(args.ns3_root, args.stage_dir, "parse_dcn_pfc_trigger.py", [args.selected_history], dry_run=args.dry_run)
    copy_matching(args.stage_dir / "parser" / "json-data-pfc", "PFC_DATA_*.json", args.output_dir, expected=3, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
