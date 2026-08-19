#!/usr/bin/env python3
from __future__ import annotations
import argparse
from plot_common import add_common_args, clear_matching, copy_file, run_bazel, temporary_input_dir

OOO_JSON = "OOO_DATA_TOPO_leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1_LOAD_80_FC_Lossy_TYPE_FbHdp2015_ERR_0.0.json"

def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 15 asymmetric OOO and retransmission.")
    add_common_args(parser)
    args = parser.parse_args()
    with temporary_input_dir(args.input_dir, "fig15", dry_run=args.dry_run) as staged:
        ooo_json = staged / OOO_JSON
        run_bazel("//main/plot_sample:plot_dcn_ooo", [ooo_json], dry_run=args.dry_run)
        trace_csv = staged / "fig15_asym_ooo_retransmission_retrans_trace.csv"
        run_bazel("//main/plot_sample:plot_dcn_unnecessary_retrans", [trace_csv], dry_run=args.dry_run)
        clear_matching(args.output_dir, "fig15*.pdf", dry_run=args.dry_run)
        copy_file(staged / OOO_JSON.replace(".json", "_dist_cdf.pdf"), args.output_dir / "fig15a_asym_reordering_distance_s3.pdf", dry_run=args.dry_run)
        copy_file(staged / "plot_fig15_asym_ooo_retransmission_retrans_trace_unnecessary_retrans.pdf", args.output_dir / "fig15b_asym_retransmission_breakdown.pdf", dry_run=args.dry_run)
    return 0
if __name__ == "__main__": raise SystemExit(main())
