#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, copy_one, select_history_rows, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 5 lossless OOO degree JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    select_history_rows(
        args.history,
        args.selected_history,
        lambda f: f[15] == "leaf_spine_128_100G_OS2" and f[17] == "AliStorage2019" and f[18] == "80",
        expected=5,
    )
    stage_parser(args.ns3_root, args.stage_dir, "parse_dcn_ooo.py", [args.selected_history], dry_run=args.dry_run)
    src = args.stage_dir / "parser" / "json-data-ooo-asy" / "OOO_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"
    copy_one(src, args.output_dir / "fig05_lossless_ooo_degree.json", dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
