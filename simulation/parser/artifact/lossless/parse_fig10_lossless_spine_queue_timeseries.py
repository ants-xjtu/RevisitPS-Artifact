#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_one, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 10 lossless spine queue time-series JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"figure10"}, algorithms={"AR"}, expected=1)
    stage_parser(
        args.ns3_root,
        args.stage_dir,
        "parse_single_spine_qlen.py",
        [args.selected_history, "--n_leaf", 8, "--n_spine", 16, "--servers_per_leaf", 16],
        dry_run=args.dry_run,
    )
    src = args.stage_dir / "parser" / "json-data-spine-qlen-by-port" / "QLEN_DATA_TOPO_leaf_spine_L8_S16_400G_OS1_LOAD_22469485_FC_Lossless_TYPE_Alltoall_ERR_0.0.json"
    copy_one(src, args.output_dir / "fig10_lossless_spine_queue_timeseries.json", dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
