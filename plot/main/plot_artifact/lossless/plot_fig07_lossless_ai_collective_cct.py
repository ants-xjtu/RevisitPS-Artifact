#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, first_pdf, run_bazel, temporary_workdir


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 7 lossless AI collective CCT.")
    add_common_args(parser)
    args = parser.parse_args()
    panels = [
        ("a", "lossless-low-incast", "low_incast"),
        ("b", "lossless-high-incast", "high_incast"),
    ]
    for panel, combined_group, suffix in panels:
        with temporary_workdir(f"fig07-{panel}", dry_run=args.dry_run) as stage_out:
            run_bazel(
                "//main/plot_sample:plot_sim_ai_jct_avg",
                [
                    args.input_dir,
                    "-o",
                    stage_out,
                    "--normalize",
                    "--combined-group",
                    combined_group,
                    "--raw-ytop",
                    4,
                    "--all-combos",
                ],
                dry_run=args.dry_run,
            )
            src = (
                stage_out / "combined.pdf"
                if args.dry_run
                else first_pdf(stage_out, "*.pdf")
            )
            copy_file(
                src,
                args.output_dir
                / f"fig07{panel}_lossless_ai_collective_cct_{suffix}.pdf",
                dry_run=args.dry_run,
            )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
