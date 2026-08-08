#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 6 lossless PFC pause duration.")
    add_common_args(parser)
    args = parser.parse_args()
    run_bazel("//main/plot_sample:plot_dcn_pfc_trigger", [args.input_dir], dry_run=args.dry_run)
    copy_file(args.input_dir / "grouped_pfc_comparison_total_duration_ns.pdf", args.output_dir / "fig06_lossless_pfc_pause_duration.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
