#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from artifact_common import add_common_args, copy_matching, select_manifest_history, stage_parser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 15 asymmetric OOO and retransmission data.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"figure15"}, expected=16)
    ooo_stage = args.stage_dir / "ooo"
    stage_parser(args.ns3_root, ooo_stage, "parse_dcn_ooo.py", [args.selected_history], dry_run=args.dry_run)
    copy_matching(ooo_stage / "parser" / "json-data-ooo-asy", "OOO_DATA_*.json", args.output_dir, dry_run=args.dry_run)

    retrans_history = args.output_dir / "fig15_asym_ooo_retransmission.history"
    if args.dry_run:
        print("COPY", args.selected_history, retrans_history)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.selected_history, retrans_history)
    retrans_stage = args.stage_dir / "retrans"
    stage_parser(args.ns3_root, retrans_stage, "parse_unnecc_retrans.py", [retrans_history], dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
