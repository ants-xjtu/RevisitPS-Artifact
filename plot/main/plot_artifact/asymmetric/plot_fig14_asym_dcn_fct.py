#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import (
    add_common_args,
    clear_matching,
    copy_file,
    first_matching,
    run_bazel,
    temporary_input_dir,
)


PANELS = [
    ("a", "s1", "AsymFail1pct"),
    ("b", "s2", "AsymFail10pct"),
    ("c", "s3", "AsymBw10pct_R0.5"),
    ("d", "s4", "AsymBw20pct_R0.5"),
]

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 14 asymmetric DCN P99 FCT panels.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig14", dry_run=args.dry_run) as staged:
        run_bazel(
            "//main/plot_sample:plot_dcn_rto_fct",
            [staged, "--metric", "p99", "--asymmetric-paper-p99-axes"],
            dry_run=args.dry_run,
        )
        clear_matching(args.output_dir, "fig14*.pdf", dry_run=args.dry_run)
        for panel, scenario, topology_marker in PANELS:
            source = (
                staged / f"DATA_*{topology_marker}*_p99.pdf"
                if args.dry_run
                else first_matching(staged, f"DATA_*{topology_marker}*_p99.pdf")
            )
            copy_file(
                source,
                args.output_dir / f"fig14{panel}_asym_dcn_p99_fct_{scenario}.pdf",
                dry_run=args.dry_run,
            )
    return 0
if __name__ == "__main__": raise SystemExit(main())
