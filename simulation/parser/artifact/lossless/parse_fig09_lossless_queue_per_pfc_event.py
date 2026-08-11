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


OUTPUT = "fig09_lossless_queue_per_pfc_event"
SOURCE = "PFC_INCAST_DATA_TOPO_leaf_spine_L8_S16_100G_OS1_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 9 queue per PFC event.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig09-history", dry_run=args.dry_run) as work:
        selected = work / "figure9.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure9"},
            topologies={"leaf_spine_L8_S16_100G_OS1"},
            workloads={"AliStorage2019"},
            group_sizes={"1"},
            expected=5,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_pfc_incast.py",
            [selected],
            dry_run=args.dry_run,
        ) as stage:
            copy_one(
                stage / "parser" / "json-data-pfc-incast-workload" / SOURCE,
                paths.output_dir / f"{OUTPUT}.json",
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
