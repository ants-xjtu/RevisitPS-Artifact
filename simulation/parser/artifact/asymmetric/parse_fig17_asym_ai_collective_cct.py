#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_matching, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 17 asymmetric AI collective CCT JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"figure17"}, expected=48)
    stage_parser(
        args.ns3_root,
        args.stage_dir,
        "parse_jct_with_ideal.py",
        [args.selected_history, "--mode", "per_group", "--merge-timeout", "--merge-cc", "--group_size", 8, "--topology", "leaf_spine_L8_S16_100G_OS1", "--bandwidth", 100],
        dry_run=args.dry_run,
    )
    copy_matching(args.stage_dir / "parser" / "json-data-jct-with-ideal", "JCT_WITH_IDEAL_*.json", args.output_dir, dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
