#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, clear_matching, copy_file, first_matching, run_bazel, temporary_input_dir

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 16 asymmetric packet trimming vs RTO.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig16", dry_run=args.dry_run) as staged:
        run_bazel(
            "//main/plot_sample:plot_dcn_rto_fct_trim_vs_rto",
            [staged, "--legend-ncol", 2, "--legend-loc", "upper left"],
            dry_run=args.dry_run,
        )
        clear_matching(args.output_dir, "fig16*.pdf", dry_run=args.dry_run)
        for panel, metric in (("a", "avg"), ("b", "p99")):
            source = (
                staged / f"DATA_*_{metric}.pdf"
                if args.dry_run
                else first_matching(staged, f"*_{metric}.pdf")
            )
            copy_file(
                source,
                args.output_dir / f"fig16{panel}_asym_packet_trim_rto_{metric}.pdf",
                dry_run=args.dry_run,
            )
    return 0
if __name__ == "__main__": raise SystemExit(main())
