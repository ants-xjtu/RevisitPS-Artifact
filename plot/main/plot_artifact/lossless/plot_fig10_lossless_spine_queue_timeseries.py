#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 10 lossless spine queue time series.")
    parser.add_argument("--spine-id", type=int, default=136)
    add_common_args(parser)
    args = parser.parse_args()
    input_json = args.input_dir / "fig10_lossless_spine_queue_timeseries.json"
    run_bazel("//main/plot_sample:plot_single_spine_qlen", [input_json, "--spine_id", args.spine_id, "--top_n", 4, "--y_step", 200, "--smooth", 5], dry_run=args.dry_run)
    copy_file(args.input_dir / f"spine_{args.spine_id}_egress_qlen.pdf", args.output_dir / "fig10_lossless_spine_queue_timeseries.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
