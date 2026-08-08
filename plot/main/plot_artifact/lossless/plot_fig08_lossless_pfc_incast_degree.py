#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel

FILES = [
    "hadoop_pfc_incast.json",
    "rpc_pfc_incast.json",
    "storage_pfc_incast.json",
    "a2av8_pfc_incast.json",
    "a2av32_pfc_incast.json",
    "a2av128_pfc_incast.json",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 8 lossless PFC incast degree.")
    add_common_args(parser)
    args = parser.parse_args()
    prefix = args.output_dir / "fig08_lossless_pfc_incast_degree"
    inputs = [args.input_dir / name for name in FILES]
    run_bazel("//main/plot_sample:plot_dcn_pfc_incast", [*inputs, "--output-prefix", prefix], dry_run=args.dry_run)
    copy_file(args.output_dir / "fig08_lossless_pfc_incast_degree_incast_flows.pdf", args.output_dir / "fig08_lossless_pfc_incast_degree.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
