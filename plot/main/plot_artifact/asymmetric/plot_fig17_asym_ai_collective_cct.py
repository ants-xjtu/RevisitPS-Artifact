#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, clear_matching, copy_file, run_bazel, temporary_workdir

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 17 asymmetric AI collective CCT.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_workdir("fig17", dry_run=args.dry_run) as stage_out:
        run_bazel("//main/plot_sample:plot_sim_ai_jct_avg_asy", [args.input_dir, "-o", stage_out, "--normalize", "--by-scenario", "--dcqcn-only", "--hide-recovery", "--no-conga", "--all-combos", "--raw-ytop", 6.5, "--raw-ystep", 1.2, "--legend-max-rows", 4], dry_run=args.dry_run)
        clear_matching(args.output_dir, "fig17*.pdf", dry_run=args.dry_run)
        for panel, workload, suffix in (
            ("a", "Alltoall", "alltoall"),
            ("b", "RingAllreduce", "allreduce"),
        ):
            copy_file(
                stage_out / f"scenario_{workload}_lossy_norm_dcqcn.pdf",
                args.output_dir / f"fig17{panel}_asym_ai_collective_cct_{suffix}.pdf",
                dry_run=args.dry_run,
            )
    return 0
if __name__ == "__main__": raise SystemExit(main())
