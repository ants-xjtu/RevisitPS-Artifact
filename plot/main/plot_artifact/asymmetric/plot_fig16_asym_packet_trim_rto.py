#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, copy_matching, run_bazel, temporary_input_dir

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 16 asymmetric packet trimming vs RTO.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig16", dry_run=args.dry_run) as staged:
        run_bazel("//main/plot_sample:plot_dcn_rto_fct_trim_vs_rto", [staged], dry_run=args.dry_run)
        copy_matching(staged, "*.pdf", args.output_dir, "fig16_asym_packet_trim_rto", dry_run=args.dry_run)
    return 0
if __name__ == "__main__": raise SystemExit(main())
