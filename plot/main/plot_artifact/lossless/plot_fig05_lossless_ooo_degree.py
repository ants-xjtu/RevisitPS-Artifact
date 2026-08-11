#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel, temporary_input_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 5 lossless OOO degree.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig05", dry_run=args.dry_run) as staged:
        input_json = staged / "fig05_lossless_ooo_degree.json"
        run_bazel("//main/plot_sample:plot_dcn_ooo", [input_json], dry_run=args.dry_run)
        copy_file(staged / "fig05_lossless_ooo_degree_dist_cdf.pdf", args.output_dir / "fig05_lossless_ooo_degree.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
