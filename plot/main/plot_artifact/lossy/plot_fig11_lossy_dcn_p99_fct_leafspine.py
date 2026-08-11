#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, copy_matching, run_bazel, temporary_input_dir

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 11 lossy DCN FCT.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig11", dry_run=args.dry_run) as staged:
        run_bazel("//main/plot_sample:plot_dcn_rto_fct", [staged], dry_run=args.dry_run)
        copy_matching(staged, "*.pdf", args.output_dir, "fig11_lossy_dcn_p99_fct_leafspine", dry_run=args.dry_run)
    return 0
if __name__ == "__main__": raise SystemExit(main())
