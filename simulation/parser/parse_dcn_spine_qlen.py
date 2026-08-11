#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandas as pd
import argparse
import os
import json
from collections import defaultdict


NANOSECONDS_PER_SECOND = 1_000_000_000

# --- Dictionaries for mode mapping (aligned with reference script) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 5: "dcqcn_lane", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5:"WAR", 6: "LetFlow", 7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -------------------------------------------------------------------

def get_spine_node_ids(n_leaf, n_spine, servers_per_leaf):
    """Calculates the range of node IDs for spine switches based on topology."""
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf
    spine_ids = list(range(id_offset_spine, id_offset_spine + n_spine))
    return spine_ids


def read_flowgen_window_ns(config_path):
    """Read the configured traffic-generation interval and convert it to ns."""
    required = ("FLOWGEN_START_TIME", "FLOWGEN_STOP_TIME")
    values = {}
    with open(config_path, "r") as config_file:
        for line in config_file:
            fields = line.split()
            if len(fields) >= 2 and fields[0] in required:
                values[fields[0]] = float(fields[1])

    missing = [key for key in required if key not in values]
    if missing:
        raise ValueError(
            f"Missing {', '.join(missing)} in simulation config: {config_path}"
        )

    start_ns = round(values["FLOWGEN_START_TIME"] * NANOSECONDS_PER_SECOND)
    end_ns = round(values["FLOWGEN_STOP_TIME"] * NANOSECONDS_PER_SECOND)
    if end_ns < start_ns:
        raise ValueError(
            f"Invalid flow-generation interval in simulation config: {config_path}"
        )
    return start_ns, end_ns


def parse_qlen_file(
    filepath,
    spine_node_ids,
    queue_type_col,
    *,
    start_time_ns=None,
    end_time_ns=None,
    spine_port_ids=None,
):
    """
    Reads a queue length data file, filters for spine nodes, and calculates statistics for a given queue type.
    
    Returns:
        A dictionary containing time-series stats and an overall summary, or None if parsing fails.
    """
    column_names = [
        'timestamp', 'node_id', 'port_id', 'ingress_qlen', 
        'dynamic_threshold', 'egress_qlen'
    ]
    try:
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            print(f"Warning: Queue length file is empty: {filepath}. Skipping.")
            return None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print(f"Warning: Queue length file not found or is empty: {filepath}. Skipping.")
        return None
    except Exception as e:
        print(f"Error reading or parsing file {filepath}: {e}")
        return None

    spine_df = df[df['node_id'].isin(spine_node_ids)]
    if spine_port_ids is not None:
        spine_df = spine_df[spine_df['port_id'].isin(spine_port_ids)]
    if start_time_ns is not None:
        spine_df = spine_df[spine_df['timestamp'] >= start_time_ns]
    if end_time_ns is not None:
        spine_df = spine_df[spine_df['timestamp'] <= end_time_ns]
    
    if spine_df.empty or queue_type_col not in spine_df.columns:
        return None
        
    # 1. Calculate time-series statistics
    time_stats = spine_df.groupby('timestamp')[queue_type_col].agg(['mean', 'max']).reset_index()

    # 2. Calculate per-port average queue length and find the most congested ports.
    port_stats = (
        spine_df.groupby(['node_id', 'port_id'])[queue_type_col]
        .agg(['mean', 'max', 'count'])
        .reset_index()
        .sort_values(by=['mean', 'max', 'node_id', 'port_id'], ascending=[False, False, True, True])
    )
    top_congested_ports = []
    for _, row in port_stats.head(10).iterrows():
        top_congested_ports.append({
            'node_id': int(row['node_id']),
            'port_id': int(row['port_id']),
            'avg_qlen_bytes': float(row['mean']),
            'max_qlen_bytes': int(row['max']),
            'sample_count': int(row['count']),
        })
    
    # 3. Calculate overall summary statistics
    # Explicitly convert NumPy types to standard Python types for JSON compatibility.
    summary = {
        'avg_qlen_bytes': float(spine_df[queue_type_col].mean()),
        'max_qlen_bytes': int(spine_df[queue_type_col].max()),
        'p99_qlen_bytes': float(spine_df[queue_type_col].quantile(0.99)),
        'sample_count': int(len(spine_df)),
        'window_start_ns': (
            int(start_time_ns) if start_time_ns is not None else None
        ),
        'window_end_ns': int(end_time_ns) if end_time_ns is not None else None,
    }
    
    # Prepare time-series data for JSON serialization.
    time_series_data = {
        'timestamps_ns': [int(ts) for ts in time_stats['timestamp']],
        'avg_qlen_bytes': [float(val) for val in time_stats['mean']],
        'max_qlen_bytes': [int(val) for val in time_stats['max']]
    }
    
    return {
        'time_series': time_series_data,
        'summary': summary,
        'top_congested_ports': top_congested_ports,
    }

def main():
    """Main function to parse arguments, process files, and generate JSON data."""
    parser = argparse.ArgumentParser(description='Parse spine switch queue lengths and save structured data to JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the history file containing simulation configurations.')
    parser.add_argument('--n_leaf', type=int, default=8, help='Number of leaf switches in the topology.')
    parser.add_argument('--n_spine', type=int, default=8, help='Number of spine switches in the topology.')
    parser.add_argument('--servers_per_leaf', type=int, default=16, help='Number of servers connected to each leaf switch.')
    parser.add_argument(
        '--use_flowgen_window',
        action='store_true',
        help='Only include samples from FLOWGEN_START_TIME through FLOWGEN_STOP_TIME.',
    )
    parser.add_argument(
        '--spine_port_count',
        type=int,
        help='Only include physical spine ports 1 through this value.',
    )
    
    args = parser.parse_args()

    file_dir = os.path.dirname(os.path.abspath(__file__))
    json_dir = os.path.join(file_dir, "json-data-spine-qlen")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    ns3_root_dir = os.path.abspath(os.path.join(file_dir, "..")) 
    output_data_dir = os.path.join(ns3_root_dir, "mix", "output")
    
    print(f"Processing history file: {args.history_file}")
    
    map_key_to_config = defaultdict(list)

    # --- Step 1: Read history file and group configurations by a more detailed key ---
    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue
                
                # --- MODIFIED: Parse additional fields for the new grouping key ---
                config_id = parsed[1]
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]

                # Skip invalid entries
                if (lb_mode_id not in lb_modes or irn not in irn_modes):
                    continue

                # --- MODIFIED: Replicated recovery label logic from reference script ---
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"

                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                
                # --- MODIFIED: Define the new, more specific key ---
                key = (topo, netload, flow_control, load_type, error_rate)
                
                entry_details = {
                    "config_id": config_id,
                    "lb_mode": lb_mode_str,
                    "recovery": recovery_label
                }
                map_key_to_config[key].append(entry_details)

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")
                continue

    # --- Step 2: Process each group and generate a JSON file ---
    spine_ids = get_spine_node_ids(args.n_leaf, args.n_spine, args.servers_per_leaf)
    print(f"Identified Spine Node IDs: {spine_ids}")
    if args.spine_port_count is not None and args.spine_port_count < 1:
        raise SystemExit("ERROR: --spine_port_count must be positive")
    spine_port_ids = (
        list(range(1, args.spine_port_count + 1))
        if args.spine_port_count is not None
        else None
    )
    if spine_port_ids is not None:
        print(f"Included Spine Port IDs: {spine_port_ids}")

    for k, v_configs in map_key_to_config.items():
        # --- MODIFIED: Update metadata to include all key components ---
        qlen_group_data = {
            "metadata": {
                "topology": k[0],
                "network_load": k[1],
                "flow_control": k[2],
                "load_type": k[3],
                "error_rate": k[4],
            },
            "data_series": []
        }

        for entry in v_configs:
            config_id = entry["config_id"]
            qlen_file_path = os.path.join(output_data_dir, config_id, f"{config_id}_out_qlen.txt")
            start_time_ns = None
            end_time_ns = None
            if args.use_flowgen_window:
                config_path = os.path.join(output_data_dir, config_id, "config.txt")
                try:
                    start_time_ns, end_time_ns = read_flowgen_window_ns(config_path)
                except (FileNotFoundError, ValueError) as error:
                    raise SystemExit(f"ERROR: {error}") from error
            
            print(f"---> Parsing data for Config ID: {config_id}")

            parse_kwargs = {
                'start_time_ns': start_time_ns,
                'end_time_ns': end_time_ns,
                'spine_port_ids': spine_port_ids,
            }
            ingress_data = parse_qlen_file(
                qlen_file_path, spine_ids, 'ingress_qlen', **parse_kwargs
            )
            egress_data = parse_qlen_file(
                qlen_file_path, spine_ids, 'egress_qlen', **parse_kwargs
            )

            if ingress_data or egress_data:
                series_data = {
                    "load_balancing_mode": entry["lb_mode"],
                    "recovery_mechanism": entry["recovery"],
                    "sample_scope": {
                        "time_window_source": (
                            "FLOWGEN_START_TIME/FLOWGEN_STOP_TIME"
                            if args.use_flowgen_window else "all recorded samples"
                        ),
                        "start_time_ns": start_time_ns,
                        "end_time_ns": end_time_ns,
                        "spine_port_ids": spine_port_ids,
                    },
                    "ingress_data": ingress_data,
                    "egress_data": egress_data
                }
                qlen_group_data["data_series"].append(series_data)
        
        if not qlen_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid queue length data.")
            continue
            
        # --- Step 3: Save the collected data to a JSON file with a new naming scheme ---
        json_filename = os.path.join(
            json_dir, 
            f"QLEN_DATA_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        )
        print(f"Saving QLen data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(qlen_group_data, f, indent=4)
            
    print("\n✅ All files parsed successfully!")

if __name__ == "__main__":
    main()
