#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, copy_file, first_pdf, run_bazel, temporary_input_dir


PANELS = [
    (
        "a",
        "without_slow_start",
        [
            "--no-rps", "--no-trimming", "--no-rto-gbn-slowstart",
            "--p99-ymin", "30", "--p99-ymax", "1450",
            "--p99-yticks", "30", "500", "1000", "1450",
        ],
    ),
    (
        "b",
        "with_slow_start",
        [
            "--no-ecmp", "--no-conweave", "--no-drill", "--no-rps",
            "--p99-ymin", "20", "--p99-ymax", "1450",
            "--p99-yticks", "20", "100", "500", "1000", "1450",
        ],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 12 lossy DCN FCT.")
    add_common_args(parser)
    args = parser.parse_args()
    for panel, suffix, filters in PANELS:
        with temporary_input_dir(
            args.input_dir, f"fig12-{panel}", dry_run=args.dry_run
        ) as staged:
            run_bazel(
                "//main/plot_sample:plot_dcn_rto_fct",
                [staged, "--metric", "p99", *filters],
                dry_run=args.dry_run,
            )
            source = (
                staged / "figure12_p99.pdf"
                if args.dry_run
                else first_pdf(staged, "*_p99.pdf")
            )
            copy_file(
                source,
                args.output_dir
                / f"fig12{panel}_lossy_dcn_p99_fct_fattree_{suffix}.pdf",
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__": raise SystemExit(main())
