#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, run, select_manifest_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 14 asymmetric DCN FCT JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    if args.manifest is None:
        raise SystemExit("ERROR: --manifest is required")
    select_manifest_history(args.manifest, args.history, args.selected_history, figures={"figure14"}, expected=24)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run(["python3", args.ns3_root / "parser" / "parse_dcn_fct_rto.py", args.selected_history, "-o", args.output_dir], dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
