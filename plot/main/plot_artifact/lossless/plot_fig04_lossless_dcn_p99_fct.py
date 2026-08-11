#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel, temporary_input_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 4 lossless DCN P99 FCT panels.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig04", dry_run=args.dry_run) as staged:
        run_bazel("//main/plot_sample:plot_dcn_fct", [staged], dry_run=args.dry_run)
        copy_file(staged / "DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0_p99.pdf", args.output_dir / "fig04a_lossless_dcn_p99_fct_leafspine_2to1.pdf", dry_run=args.dry_run)
        copy_file(staged / "DATA_TOPO_fat_k8_100G_OS1_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0_p99.pdf", args.output_dir / "fig04b_lossless_dcn_p99_fct_fattree.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
