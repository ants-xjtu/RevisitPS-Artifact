#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel, temporary_input_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 6 lossless PFC pause duration.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig06", dry_run=args.dry_run) as staged:
        run_bazel("//main/plot_sample:plot_dcn_pfc_trigger", [staged], dry_run=args.dry_run)
        copy_file(staged / "grouped_pfc_comparison_total_duration_ns.pdf", args.output_dir / "fig06_lossless_pfc_pause_duration.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
