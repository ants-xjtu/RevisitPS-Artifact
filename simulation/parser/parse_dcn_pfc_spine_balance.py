#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import argparse
import json
import re
from collections import defaultdict

# --- Mode conversion dictionaries ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# ------------------------------------

def getFilePath():
    return os.path.dirname(os.path.abspath(__file__))

def parse_topo_params(topo_str):
    """
    Extract n_leaf and n_spine from topo name like 'leaf_spine_L8_S16_100G_OS1'.
    Returns (n_leaf, n_spine) or (None, None) if not matched.
    """
    m = re.search(r'L(\d+)_S(\d+)', topo_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

def process_pfc_log(filepath):
    """
    Parse a PFC log file (format: TimeStep NodeID NodeType IfIndex PfcType).
    Returns a list of pause interval dicts, or None on error.
    """
    if not os.path.exists(filepath):
        print(f"  Warning: PFC log file not found: {filepath}")
        return None

    rows = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                rows.append({
                    'TimeStep': int(parts[0]),
                    'NodeID':   int(parts[1]),
                    'NodeType': int(parts[2]),
                    'IfIndex':  int(parts[3]),
                    'PfcType':  int(parts[4]),
                })
    except Exception as e:
        print(f"  Error reading {filepath}: {e}")
        return None

    if not rows:
        return []

    rows.sort(key=lambda r: r['TimeStep'])
    sim_end_time = rows[-1]['TimeStep']

    # Group by (NodeID, IfIndex)
    port_events = defaultdict(list)
    for row in rows:
        port_events[(row['NodeID'], row['IfIndex'])].append(row)

    intervals = []
    for (node_id, if_index), events in port_events.items():
        last_pause_start = None
        for row in events:
            if row['PfcType'] == 1:
                if last_pause_start is None:
                    last_pause_start = row['TimeStep']
            elif row['PfcType'] == 0:
                if last_pause_start is not None:
                    intervals.append({
                        'NodeID':    node_id,
                        'IfIndex':   if_index,
                        'StartTime': last_pause_start,
                        'EndTime':   row['TimeStep'],
                    })
                    last_pause_start = None
        if last_pause_start is not None:
            intervals.append({
                'NodeID':    node_id,
                'IfIndex':   if_index,
                'StartTime': last_pause_start,
                'EndTime':   sim_end_time,
            })
    return intervals

def analyze_spine_to_leaf_balance(intervals, n_leaf, n_spine, servers_per_leaf):
    """
    Grouped by target Leaf, compute pause duration stats for all Spine ports
    connected to that Leaf (Spine-to-Leaf direction).

    Returns a dict:
    {
        "per_leaf": {
            <leaf_idx>: {
                "spine_durations": { <spine_node_id>: <total_duration_ns> },
                "stats": { mean, max, min, range, variance, std_dev, cv }
            }
        },
        "overall_summary": { mean_of_means, mean_cv, max_cv, min_cv }
    }
    """
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_spine  = n_servers_total + n_leaf

    # Aggregate total pause duration per (SpineNode, IfIndex)
    port_total = defaultdict(int)
    for iv in intervals:
        node_id  = iv['NodeID']
        if_index = iv['IfIndex']
        if node_id >= id_offset_spine:
            duration = iv['EndTime'] - iv['StartTime']
            port_total[(node_id, if_index)] += duration

    # Map each (spine_node, if_index) → target_leaf_index
    # Convention (same as plot_analyze_pfc.py): IfIndex - 1 == target leaf index
    leaf_groups = defaultdict(dict)   # leaf_idx -> {spine_node_id: total_duration}
    for (node_id, if_index), total_dur in port_total.items():
        target_leaf = if_index - 1
        if 0 <= target_leaf < n_leaf:
            leaf_groups[target_leaf][node_id] = total_dur

    if not leaf_groups:
        return None

    per_leaf_result = {}
    group_means = []
    group_cvs   = []

    for leaf_idx in sorted(leaf_groups.keys()):
        spine_durations = leaf_groups[leaf_idx]
        durations = list(spine_durations.values())

        mean_val  = sum(durations) / len(durations)
        max_val   = max(durations)
        min_val   = min(durations)
        range_val = 0
        var_val   = 0.0
        std_val   = 0.0
        cv_val    = 0.0

        if len(durations) > 1 and max_val != min_val:
            range_val = max_val - min_val
            var_val   = sum((d - mean_val) ** 2 for d in durations) / len(durations)
            std_val   = var_val ** 0.5
            cv_val    = std_val / mean_val if mean_val > 0 else 0.0

        group_means.append(mean_val)
        group_cvs.append(cv_val)

        per_leaf_result[leaf_idx] = {
            "spine_durations": {str(k): v for k, v in sorted(spine_durations.items())},
            "stats": {
                "mean_ns":     round(mean_val, 4),
                "max_ns":      max_val,
                "min_ns":      min_val,
                "range_ns":    range_val,
                "variance":    round(var_val, 4),
                "std_dev_ns":  round(std_val, 4),
                "cv":          round(cv_val, 6),
            }
        }

    overall_summary = {
        "mean_of_means_ns": round(sum(group_means) / len(group_means), 4),
        "mean_cv":          round(sum(group_cvs)   / len(group_cvs),   6),
        "max_cv":           round(max(group_cvs), 6),
        "min_cv":           round(min(group_cvs), 6),
    }

    return {
        "per_leaf":        {str(k): v for k, v in per_leaf_result.items()},
        "overall_summary": overall_summary,
    }

def main():
    parser = argparse.ArgumentParser(
        description='Parse PFC pause logs and analyze Spine-to-Leaf pause balance per Leaf group.')
    parser.add_argument('history_file', type=str, help='Path to the history file to process.')
    parser.add_argument('--servers-per-leaf', type=int, default=16,
                        help='Number of servers per leaf switch (default: 16).')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-pfc-spine-balance")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    ns3_root_dir = os.path.abspath(os.path.join(file_dir, ".."))
    output_dir   = os.path.join(ns3_root_dir, "mix", "output")

    print(f"Processing history file: {args.history_file}")
    print("Analysis: Spine-to-Leaf PFC pause balance grouped by target Leaf.\n")

    map_key_to_config = defaultdict(list)

    # --- Step 1: Read history file and group lossless configurations ---
    with open(args.history_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('./'):
                continue
            try:
                parsed = line.split(',')
                if len(parsed) < 22:
                    continue

                config_id  = parsed[1]
                lb_mode_id = int(parsed[3])
                ar_mode    = parsed[4]
                pfc_val    = int(parsed[10])
                irn        = int(parsed[11])
                topo       = parsed[15]
                load_type  = parsed[17]
                netload    = parsed[18]
                error_rate = parsed[19]

                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"

                lb_mode_str  = lb_modes.get(lb_mode_id, 'UnknownLB')
                flow_control = "Lossless" if pfc_val == 1 else "Lossy"

                if flow_control == "Lossless":
                    key = (topo, netload, flow_control, load_type, error_rate)
                    map_key_to_config[key].append({
                        "config_id": config_id,
                        "lb_mode":   lb_mode_str,
                        "recovery":  recovery_label,
                    })
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")
                continue

    # --- Step 2: Process each group and generate a JSON file ---
    for k, v_configs in map_key_to_config.items():
        topo = k[0]
        n_leaf, n_spine = parse_topo_params(topo)
        if n_leaf is None:
            print(f"Warning: Cannot extract n_leaf/n_spine from topo '{topo}', skipping group {k}.")
            continue

        servers_per_leaf = args.servers_per_leaf
        print(f"\n=== Group: topo={topo}, netload={k[1]}, {k[2]}, {k[3]}, err={k[4]} ===")
        print(f"    Topology params: n_leaf={n_leaf}, n_spine={n_spine}, servers_per_leaf={servers_per_leaf}")

        group_data = {
            "metadata": {
                "topology":      k[0],
                "network_load":  k[1],
                "flow_control":  k[2],
                "load_type":     k[3],
                "error_rate":    k[4],
                "n_leaf":        n_leaf,
                "n_spine":       n_spine,
                "servers_per_leaf": servers_per_leaf,
            },
            "data_series": []
        }

        for entry in v_configs:
            config_id = entry["config_id"]
            pfc_log   = os.path.join(output_dir, config_id, f"{config_id}_out_pfc.txt")

            print(f"  --> Config {config_id} [{entry['lb_mode']} / {entry['recovery']}]")

            intervals = process_pfc_log(pfc_log)
            if intervals is None:
                print(f"      Skipping: file not found or parse error.")
                continue
            if len(intervals) == 0:
                print(f"      No PFC pause intervals found.")
                balance_result = None
            else:
                balance_result = analyze_spine_to_leaf_balance(
                    intervals, n_leaf, n_spine, servers_per_leaf)
                if balance_result is None:
                    print(f"      No Spine-to-Leaf pause data found.")

            series = {
                "load_balancing_mode":  entry["lb_mode"],
                "recovery_mechanism":   entry["recovery"],
                "config_id":            config_id,
                "total_pause_intervals": len(intervals),
                "spine_to_leaf_balance": balance_result,
            }
            group_data["data_series"].append(series)

        if not group_data["data_series"]:
            print(f"  Skipping group {k}: no valid data.")
            continue

        # --- Step 3: Save JSON ---
        json_filename = os.path.join(
            json_dir,
            f"PFC_SPINE_BALANCE_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        )
        print(f"  Saving to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(group_data, f, indent=4)

    print("\n✅ All PFC spine balance files parsed successfully!")

if __name__ == "__main__":
    main()
