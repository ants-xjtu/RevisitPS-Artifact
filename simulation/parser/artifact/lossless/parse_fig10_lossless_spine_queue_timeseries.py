#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    copy_one,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "fig10_lossless_spine_queue_timeseries"
SOURCE = "QLEN_DATA_TOPO_leaf_spine_L8_S16_400G_OS1_LOAD_22469485_FC_Lossless_TYPE_Alltoall_ERR_0.0.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 10 spine queues.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig10-history", dry_run=args.dry_run) as work:
        selected = work / "figure10.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure10"},
            algorithms={"AR"},
            expected=1,
            dry_run=args.dry_run,
        )
        backend_args = [
            selected,
            "--n_leaf", 8,
            "--n_spine", 16,
            "--servers_per_leaf", 16,
        ]
        with temporary_parser_stage(
            args.ns3_root,
            "parse_single_spine_qlen.py",
            backend_args,
            dry_run=args.dry_run,
        ) as stage:
            copy_one(
                stage / "parser" / "json-data-spine-qlen-by-port" / SOURCE,
                paths.output_dir / f"{OUTPUT}.json",
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
