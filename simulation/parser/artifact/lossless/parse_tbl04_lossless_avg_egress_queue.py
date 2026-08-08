#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, build_table4, copy_one, select_history_rows, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 4 lossless average egress queue JSON/table.")
    parser.add_argument("--table-dir", required=True, type=str)
    add_common_args(parser)
    args = parser.parse_args()
    select_history_rows(
        args.history,
        args.selected_history,
        lambda f: f[15] == "leaf_spine_128_100G_OS2" and f[17] == "AliStorage2019" and f[18] == "80",
        expected=5,
    )
    stage_parser(
        args.ns3_root,
        args.stage_dir,
        "parse_dcn_spine_qlen.py",
        [args.selected_history, "--n_leaf", 8, "--n_spine", 8, "--servers_per_leaf", 16],
        dry_run=args.dry_run,
    )
    src = args.stage_dir / "parser" / "json-data-spine-qlen" / "QLEN_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"
    dst = args.output_dir / "tbl04_lossless_avg_egress_queue.json"
    copy_one(src, dst, dry_run=args.dry_run)
    build_table4(dst, __import__("pathlib").Path(args.table_dir), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
