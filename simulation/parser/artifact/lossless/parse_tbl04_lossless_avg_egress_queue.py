#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    build_table4,
    copy_one,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "tbl04_lossless_avg_egress_queue"
SOURCE = "QLEN_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 4 egress queues.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("tbl04-history", dry_run=args.dry_run) as work:
        selected = work / "table4.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"table4"},
            expected=5,
            dry_run=args.dry_run,
        )
        backend_args = [
            selected,
            "--n_leaf", 8,
            "--n_spine", 8,
            "--servers_per_leaf", 16,
        ]
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_spine_qlen.py",
            backend_args,
            dry_run=args.dry_run,
        ) as stage:
            destination = paths.output_dir / f"{OUTPUT}.json"
            copy_one(
                stage / "parser" / "json-data-spine-qlen" / SOURCE,
                destination,
                dry_run=args.dry_run,
            )
            build_table4(
                destination, paths.table_dir, dry_run=args.dry_run
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
