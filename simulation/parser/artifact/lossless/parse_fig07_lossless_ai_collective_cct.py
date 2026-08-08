#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_matching, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 7 lossless AI collective CCT JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"figure7"}, expected=47)
    stage_parser(
        args.ns3_root,
        args.stage_dir,
        "parse_jct_with_ideal.py",
        [args.selected_history, "--mode", "vs_groupsize", "--merge-timeout", "--merge-cc", "--group_size", 8, "--topology", "leaf_spine_L8_S16_400G_OS1", "--bandwidth", 400],
        dry_run=args.dry_run,
    )
    copy_matching(args.stage_dir / "parser" / "json-data-jct-vs-groupsize" / "test-trim", "JCT_VS_GROUPSIZE_*.json", args.output_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
