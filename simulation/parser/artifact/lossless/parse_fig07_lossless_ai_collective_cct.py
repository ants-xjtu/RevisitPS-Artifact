#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    copy_matching,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "fig07_lossless_ai_collective_cct"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 7 lossless CCT.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig07-history", dry_run=args.dry_run) as work:
        selected = work / "figure7.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure7"},
            expected=47,
            dry_run=args.dry_run,
        )
        backend_args = [
            selected,
            "--mode", "vs_groupsize",
            "--merge-timeout",
            "--merge-cc",
            "--group_size", 8,
            "--topology", "leaf_spine_L8_S16_400G_OS1",
            "--bandwidth", 400,
        ]
        with temporary_parser_stage(
            args.ns3_root,
            "parse_jct_with_ideal.py",
            backend_args,
            dry_run=args.dry_run,
        ) as stage:
            copy_matching(
                stage / "parser" / "json-data-jct-vs-groupsize" / "test-trim",
                "JCT_VS_GROUPSIZE_*.json",
                paths.output_dir,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
