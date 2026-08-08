#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, copy_matching, run_bazel

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 14 asymmetric DCN FCT.")
    add_common_args(parser)
    args = parser.parse_args()
    run_bazel("//main/plot_sample:plot_dcn_rto_fct", [args.input_dir], dry_run=args.dry_run)
    copy_matching(args.input_dir, "*.pdf", args.output_dir, "fig14_asym_dcn_fct", dry_run=args.dry_run)
    return 0
if __name__ == "__main__": raise SystemExit(main())
