#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, copy_matching, run_bazel, temporary_workdir

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 13 lossy AI collective CCT.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_workdir("fig13", dry_run=args.dry_run) as stage_out:
        run_bazel("//main/plot_sample:plot_sim_ai_jct_avg", [args.input_dir, "-o", stage_out, "--normalize", "--combined", "--all-combos"], dry_run=args.dry_run)
        copy_matching(stage_out, "*.pdf", args.output_dir, "fig13_lossy_ai_collective_cct", dry_run=args.dry_run)
    return 0
if __name__ == "__main__": raise SystemExit(main())
