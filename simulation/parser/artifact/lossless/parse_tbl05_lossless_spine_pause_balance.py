#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    build_table5,
    copy_matching,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "tbl05_lossless_spine_pause_balance"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 5 spine pause balance.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("tbl05-history", dry_run=args.dry_run) as work:
        selected = work / "table5.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"table5"},
            topologies={"leaf_spine_L8_S16_100G_OS1"},
            workloads={"AliStorage2019"},
            group_sizes={"1"},
            expected=5,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_pfc_spine_balance.py",
            [selected, "--servers-per-leaf", 16],
            dry_run=args.dry_run,
        ) as stage:
            copy_matching(
                stage / "parser" / "json-data-pfc-spine-balance",
                "PFC_SPINE_BALANCE_*.json",
                paths.output_dir,
                expected=1,
                dry_run=args.dry_run,
            )
            build_table5(
                paths.output_dir, paths.table_dir, dry_run=args.dry_run
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
