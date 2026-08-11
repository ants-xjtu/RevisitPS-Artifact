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


OUTPUT = "fig06_lossless_pfc_pause_duration"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 6 lossless PFC pauses.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig06-history", dry_run=args.dry_run) as work:
        selected = work / "figure6.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure6"},
            expected=15,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_pfc_trigger.py",
            [selected],
            dry_run=args.dry_run,
        ) as stage:
            copy_matching(
                stage / "parser" / "json-data-pfc",
                "PFC_DATA_*.json",
                paths.output_dir,
                expected=3,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
