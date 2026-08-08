#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from collections import defaultdict

import pandas as pd


cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 5: "dcqcn_lane", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow",
    7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}


def load_spine_dl_util_df(filepath):
    column_names = ["timestamp", "node_id", "port_id", "txbyte", "link_bps"]
    try:
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            print(f"Warning: Spine downlink file is empty: {filepath}. Skipping.")
            return None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print(f"Warning: Spine downlink file not found or is empty: {filepath}. Skipping.")
        return None
    except Exception as e:
        print(f"Error reading or parsing file {filepath}: {e}")
        return None

    df = df.sort_values(["node_id", "port_id", "timestamp"]).copy()
    df["delta_time_ns"] = df.groupby(["node_id", "port_id"])["timestamp"].diff()
    df["delta_txbyte"] = df.groupby(["node_id", "port_id"])["txbyte"].diff()
    df = df[(df["delta_time_ns"] > 0) & (df["delta_txbyte"] >= 0)].copy()
    if df.empty:
        print(f"Warning: No valid delta samples in {filepath}. Skipping.")
        return None

    df["util_percent"] = (
        df["delta_txbyte"] * 8.0 / (df["delta_time_ns"] * 1e-9) / df["link_bps"] * 100.0
    )
    return df


def summarize_spine_dl_util_df(df, analysis_window=None):
    if analysis_window is not None:
        start_ns, end_ns = analysis_window
        df = df[(df["timestamp"] >= start_ns) & (df["timestamp"] <= end_ns)].copy()
        if df.empty:
            return None

    time_stats = df.groupby("timestamp")["util_percent"].agg(["mean", "max"]).reset_index()

    port_stats = (
        df.groupby(["node_id", "port_id"])["util_percent"]
        .agg(["mean", "max", "count"])
        .reset_index()
        .sort_values(by=["mean", "max", "node_id", "port_id"], ascending=[False, False, True, True])
    )
    top_congested_ports = []
    for _, row in port_stats.head(10).iterrows():
        top_congested_ports.append({
            "node_id": int(row["node_id"]),
            "port_id": int(row["port_id"]),
            "avg_util_percent": float(row["mean"]),
            "max_util_percent": float(row["max"]),
            "sample_count": int(row["count"]),
        })

    leaf_balance = []
    for port_id, group in port_stats.groupby("port_id"):
        per_spine_avg = group["mean"].astype(float)
        mean_util = float(per_spine_avg.mean())
        std_util = float(per_spine_avg.std(ddof=0))
        min_util = float(per_spine_avg.min())
        max_util = float(per_spine_avg.max())
        util_spread = float(max_util - min_util)
        cv = float(std_util / mean_util) if mean_util > 0 else 0.0
        denom = float(len(per_spine_avg) * (per_spine_avg.pow(2).sum()))
        jain = float((per_spine_avg.sum() ** 2) / denom) if denom > 0 else 0.0
        leaf_balance.append({
            "leaf_port_id": int(port_id),
            "num_spines": int(len(per_spine_avg)),
            "avg_util_percent_across_spines": mean_util,
            "min_util_percent": min_util,
            "max_util_percent": max_util,
            "std_util_percent": std_util,
            "max_minus_min_util_percent": util_spread,
            "cv": cv,
            "jain_fairness": jain,
        })
    leaf_balance.sort(key=lambda item: item["leaf_port_id"])

    avg_cv = float(sum(item["cv"] for item in leaf_balance) / len(leaf_balance)) if leaf_balance else 0.0
    max_cv_item = max(leaf_balance, key=lambda item: item["cv"]) if leaf_balance else None
    avg_jain = (
        float(sum(item["jain_fairness"] for item in leaf_balance) / len(leaf_balance))
        if leaf_balance else 0.0
    )
    min_jain_item = min(leaf_balance, key=lambda item: item["jain_fairness"]) if leaf_balance else None
    avg_spread = (
        float(sum(item["max_minus_min_util_percent"] for item in leaf_balance) / len(leaf_balance))
        if leaf_balance else 0.0
    )
    max_spread_item = (
        max(leaf_balance, key=lambda item: item["max_minus_min_util_percent"])
        if leaf_balance else None
    )
    hottest_leaf_item = (
        max(leaf_balance, key=lambda item: item["avg_util_percent_across_spines"])
        if leaf_balance else None
    )
    coldest_leaf_item = (
        min(leaf_balance, key=lambda item: item["avg_util_percent_across_spines"])
        if leaf_balance else None
    )
    std_of_leaf_avg_util = (
        float(pd.Series([item["avg_util_percent_across_spines"] for item in leaf_balance]).std(ddof=0))
        if leaf_balance else 0.0
    )
    most_unbalanced_leafs = sorted(
        leaf_balance, key=lambda item: (-item["cv"], item["leaf_port_id"])
    )[:3]

    summary = {
        "avg_util_percent": float(df["util_percent"].mean()),
        "max_util_percent": float(df["util_percent"].max()),
        "p99_util_percent": float(df["util_percent"].quantile(0.99)),
    }

    time_series_data = {
        "timestamps_ns": [int(ts) for ts in time_stats["timestamp"]],
        "avg_util_percent": [float(val) for val in time_stats["mean"]],
        "max_util_percent": [float(val) for val in time_stats["max"]],
    }

    return {
        "analysis_window_ns": {
            "start": int(df["timestamp"].min()),
            "end": int(df["timestamp"].max()),
        },
        "time_series": time_series_data,
        "summary": summary,
        "top_congested_ports": top_congested_ports,
        "leaf_balance_uniformity": leaf_balance,
        "leaf_balance_summary": {
            "avg_cv": avg_cv,
            "max_cv": max_cv_item["cv"] if max_cv_item else 0.0,
            "max_cv_leaf_port_id": max_cv_item["leaf_port_id"] if max_cv_item else None,
            "avg_jain_fairness": avg_jain,
            "min_jain_fairness": min_jain_item["jain_fairness"] if min_jain_item else 0.0,
            "min_jain_leaf_port_id": min_jain_item["leaf_port_id"] if min_jain_item else None,
            "avg_max_minus_min_util_percent": avg_spread,
            "max_max_minus_min_util_percent": (
                max_spread_item["max_minus_min_util_percent"] if max_spread_item else 0.0
            ),
            "max_spread_leaf_port_id": max_spread_item["leaf_port_id"] if max_spread_item else None,
            "std_of_leaf_avg_util_percent": std_of_leaf_avg_util,
            "hottest_leaf_avg_util_percent": (
                hottest_leaf_item["avg_util_percent_across_spines"] if hottest_leaf_item else 0.0
            ),
            "hottest_leaf_port_id": hottest_leaf_item["leaf_port_id"] if hottest_leaf_item else None,
            "coldest_leaf_avg_util_percent": (
                coldest_leaf_item["avg_util_percent_across_spines"] if coldest_leaf_item else 0.0
            ),
            "coldest_leaf_port_id": coldest_leaf_item["leaf_port_id"] if coldest_leaf_item else None,
            "most_unbalanced_leafs_by_cv": [
                {
                    "leaf_port_id": item["leaf_port_id"],
                    "cv": item["cv"],
                    "jain_fairness": item["jain_fairness"],
                    "max_minus_min_util_percent": item["max_minus_min_util_percent"],
                }
                for item in most_unbalanced_leafs
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse spine downlink monitor files and save utilization data to JSON files."
    )
    parser.add_argument("history_file", type=str, help="Path to the history file containing simulation configurations.")
    parser.add_argument("--start-ms", type=float, default=None,
                        help="Absolute analysis window start time in milliseconds.")
    parser.add_argument("--end-ms", type=float, default=None,
                        help="Absolute analysis window end time in milliseconds.")
    parser.add_argument("--trim-start-frac", type=float, default=0.10,
                        help="Fraction of the shared time window to exclude from the beginning.")
    parser.add_argument("--trim-end-frac", type=float, default=0.10,
                        help="Fraction of the shared time window to exclude from the end.")
    args = parser.parse_args()

    file_dir = os.path.dirname(os.path.abspath(__file__))
    json_dir = os.path.join(file_dir, "json-data-spine-dl-util")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    ns3_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
    output_data_dir = os.path.join(ns3_root_dir, "mix", "output")

    print(f"Processing history file: {args.history_file}")

    map_key_to_config = defaultdict(list)

    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line:
                continue

            try:
                parsed = line.split(",")
                if len(parsed) < 22:
                    continue

                config_id = parsed[1]
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]

                if lb_mode_id not in lb_modes or irn not in irn_modes:
                    continue

                recovery_label = irn_modes.get(irn)
                if ar_mode == "1":
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"

                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                key = (topo, netload, flow_control, load_type, error_rate)

                map_key_to_config[key].append({
                    "config_id": config_id,
                    "lb_mode": lb_mode_str,
                    "recovery": recovery_label,
                })
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")
                continue

    for key, configs in map_key_to_config.items():
        util_group_data = {
            "metadata": {
                "topology": key[0],
                "network_load": key[1],
                "flow_control": key[2],
                "load_type": key[3],
                "error_rate": key[4],
            },
            "data_series": [],
        }
        loaded_series = []

        for entry in configs:
            config_id = entry["config_id"]
            spine_dl_file_path = os.path.join(output_data_dir, config_id, f"{config_id}_out_spine_dl.txt")

            print(f"---> Parsing spine downlink utilization for Config ID: {config_id}")
            util_df = load_spine_dl_util_df(spine_dl_file_path)
            if util_df is None:
                continue
            loaded_series.append({
                "config_id": config_id,
                "lb_mode": entry["lb_mode"],
                "recovery": entry["recovery"],
                "util_df": util_df,
                "start_ns": int(util_df["timestamp"].min()),
                "end_ns": int(util_df["timestamp"].max()),
            })

        if not loaded_series:
            print(f"Skipping group {key} due to no valid spine downlink utilization data.")
            continue

        common_start_ns = max(item["start_ns"] for item in loaded_series)
        common_end_ns = min(item["end_ns"] for item in loaded_series)
        if common_end_ns <= common_start_ns:
            print(f"Skipping group {key} due to empty shared time window.")
            continue

        if (args.start_ms is None) ^ (args.end_ms is None):
            print("Skipping group because --start-ms and --end-ms must be provided together.")
            continue

        if args.start_ms is not None and args.end_ms is not None:
            trimmed_start_ns = int(round(args.start_ms * 1e6))
            trimmed_end_ns = int(round(args.end_ms * 1e6))
            if trimmed_start_ns < common_start_ns or trimmed_end_ns > common_end_ns:
                print(
                    f"Skipping group {key} because requested window "
                    f"{args.start_ms:.3f}ms..{args.end_ms:.3f}ms is outside the shared range "
                    f"{common_start_ns / 1e6:.3f}ms..{common_end_ns / 1e6:.3f}ms."
                )
                continue
        else:
            shared_span_ns = common_end_ns - common_start_ns
            trimmed_start_ns = int(common_start_ns + shared_span_ns * args.trim_start_frac)
            trimmed_end_ns = int(common_end_ns - shared_span_ns * args.trim_end_frac)
        if trimmed_end_ns <= trimmed_start_ns:
            print(f"Skipping group {key} due to empty trimmed time window.")
            continue

        util_group_data["metadata"]["shared_analysis_window_ns"] = {
            "common_start": common_start_ns,
            "common_end": common_end_ns,
            "trimmed_start": trimmed_start_ns,
            "trimmed_end": trimmed_end_ns,
            "trim_start_frac": args.trim_start_frac if args.start_ms is None else None,
            "trim_end_frac": args.trim_end_frac if args.start_ms is None else None,
            "start_ms": args.start_ms,
            "end_ms": args.end_ms,
        }

        for item in loaded_series:
            util_data = summarize_spine_dl_util_df(
                item["util_df"],
                analysis_window=(trimmed_start_ns, trimmed_end_ns),
            )
            if util_data is None:
                continue

            util_group_data["data_series"].append({
                "config_id": item["config_id"],
                "load_balancing_mode": item["lb_mode"],
                "recovery_mechanism": item["recovery"],
                "spine_downlink_utilization": util_data,
            })

        if not util_group_data["data_series"]:
            print(f"Skipping group {key} due to no valid spine downlink utilization data.")
            continue

        print(
            f"Average spine downlink utilization from "
            f"{trimmed_start_ns / 1e6:.3f} ms to {trimmed_end_ns / 1e6:.3f} ms:"
        )
        for series in util_group_data["data_series"]:
            avg_util = series["spine_downlink_utilization"]["summary"]["avg_util_percent"]
            print(
                f"  {series['config_id']} "
                f"{series['load_balancing_mode']} "
                f"{series['recovery_mechanism']}: "
                f"{avg_util:.3f}%"
            )
            summary = series["spine_downlink_utilization"]["leaf_balance_summary"]
            print(
                f"    Leaf balance summary: "
                f"avg_cv={summary['avg_cv']:.4f}, "
                f"max_cv={summary['max_cv']:.4f}(leaf_port={summary['max_cv_leaf_port_id']}), "
                f"avg_jain={summary['avg_jain_fairness']:.4f}, "
                f"min_jain={summary['min_jain_fairness']:.4f}(leaf_port={summary['min_jain_leaf_port_id']}), "
                f"avg_spread={summary['avg_max_minus_min_util_percent']:.3f}%, "
                f"max_spread={summary['max_max_minus_min_util_percent']:.3f}%(leaf_port={summary['max_spread_leaf_port_id']})"
            )
            print(
                f"    Leaf avg util spread across leafs: "
                f"std={summary['std_of_leaf_avg_util_percent']:.3f}%, "
                f"hottest=leaf_port {summary['hottest_leaf_port_id']} ({summary['hottest_leaf_avg_util_percent']:.3f}%), "
                f"coldest=leaf_port {summary['coldest_leaf_port_id']} ({summary['coldest_leaf_avg_util_percent']:.3f}%)"
            )
            print("    Most unbalanced leafs by cv:")
            for item in summary["most_unbalanced_leafs_by_cv"]:
                print(
                    f"      leaf_port={item['leaf_port_id']} "
                    f"cv={item['cv']:.4f} "
                    f"jain={item['jain_fairness']:.4f} "
                    f"spread={item['max_minus_min_util_percent']:.3f}%"
                )
            leaf_balance = series["spine_downlink_utilization"]["leaf_balance_uniformity"]
            print("    Leaf balance uniformity:")
            for item in leaf_balance:
                print(
                    f"      leaf_port={item['leaf_port_id']} "
                    f"avg={item['avg_util_percent_across_spines']:.3f}% "
                    f"min={item['min_util_percent']:.3f}% "
                    f"max={item['max_util_percent']:.3f}% "
                    f"spread={item['max_minus_min_util_percent']:.3f}% "
                    f"cv={item['cv']:.4f} "
                    f"jain={item['jain_fairness']:.4f}"
                )

        json_filename = os.path.join(
            json_dir,
            f"SPINE_DL_UTIL_TOPO_{key[0]}_LOAD_{key[1]}_FC_{key[2]}_TYPE_{key[3]}_ERR_{key[4]}.json",
        )
        print(f"Saving spine downlink utilization data to: {json_filename}")
        with open(json_filename, "w") as f:
            json.dump(util_group_data, f, indent=4)

    print("\n✅ All files parsed successfully!")


if __name__ == "__main__":
    main()
