#!/usr/bin/python3

import subprocess
import os
import sys
import argparse
import math
import json
import pandas as pd
import warnings
from collections import defaultdict

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
lb_modes = {
    # 补上了 5: "WAR"
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -----------------------------------------

def getFilePath():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def analyze_rto_file(file_path):
    """
    Parses a single FCT file and returns a dictionary with RTO analysis results.
    """
    analysis_results = {}

    # Define column names for the FCT file
    col_names = [
        'col1', 'col2', 'col3', 'col4', 'flow_size', 'start_time',
        'fct', 'oracle_fct', 'rto_count'
    ]
    try:
        df = pd.read_csv(file_path, sep=' ', header=None, names=col_names, on_bad_lines='skip')
        df.dropna(inplace=True)
        df = df.astype({
            'flow_size': int, 'start_time': int, 'fct': int, 'rto_count': int
        })
    except Exception:
        return None

    total_flows = len(df)
    if total_flows == 0:
        return None
        
    rto_flows_df = df[df['rto_count'] > 0]
    num_rto_flows = len(rto_flows_df)

    # --- 1. Overall RTO Statistics ---
    analysis_results['overall_stats'] = {
        'total_flows': total_flows,
        'rto_flows': num_rto_flows,
        'rto_ratio_percent': (num_rto_flows / total_flows) * 100 if total_flows > 0 else 0
    }

    # --- NEW: 2. Detailed RTO Count Statistics ---
    total_rto_events = df['rto_count'].sum()
    analysis_results['detailed_rto_counts'] = {
        'total_rto_events': int(total_rto_events),
        'avg_rto_per_flow': total_rto_events / total_flows if total_flows > 0 else 0,
        'avg_rto_per_rto_flow': total_rto_events / num_rto_flows if num_rto_flows > 0 else 0,
        'max_rto_in_single_flow': int(df['rto_count'].max())
    }

    # --- NEW: 3. RTO Count Distribution ---
    rto_distribution = df['rto_count'].value_counts().sort_index().reset_index()
    rto_distribution.columns = ['rto_count', 'num_flows']
    # analysis_results['rto_count_distribution'] = rto_distribution.to_dict('records')

    # --- 4. Per-Flow-Size-Bucket RTO Statistics (ENHANCED) ---
    size_bins = [0, 1024, 4*1024, 10*1024, 40*1024, 100*1024, 400*1024, 1024*1024, float('inf')]
    size_labels = [
        '0-1KB', '1-4KB', '4-10KB', '10-40KB', '40-100KB',
        '100-400KB', '400KB-1MB', '>1MB'
    ]
    df['size_bucket'] = pd.cut(df['flow_size'], bins=size_bins, labels=size_labels, right=False)
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        size_bucket_stats = df.groupby('size_bucket', observed=False).apply(lambda x: pd.Series({
            'total_flows': len(x),
            'rto_flows': (x['rto_count'] > 0).sum(),
            'total_rto_events': x['rto_count'].sum(),
            'avg_rto_per_rto_flow': x[x['rto_count'] > 0]['rto_count'].mean() if (x['rto_count'] > 0).any() else 0
        })).reset_index()
    
    size_bucket_stats['rto_ratio_percent'] = size_bucket_stats.apply(
        lambda row: (row['rto_flows'] / row['total_flows']) * 100 if row['total_flows'] > 0 else 0,
        axis=1
    )
    analysis_results['by_flow_size'] = size_bucket_stats.to_dict('records')

    # # --- 5. RTO Flow Completion Time (Absolute Timestamp) Distribution ---
    # df['absolute_completion_time'] = df['start_time'] + df['fct']
    # if num_rto_flows > 0:
    #     rto_flows_df = df[df['rto_count'] > 0].copy()
    #     time_bins = pd.cut(rto_flows_df['absolute_completion_time'], bins=10)
    #     time_dist = time_bins.value_counts().sort_index().reset_index()
    #     time_dist.columns = ['completion_time_bucket', 'num_rto_flows']
    #     time_dist['completion_time_bucket'] = time_dist['completion_time_bucket'].astype(str)
    #     analysis_results['rto_flow_completion_time_distribution'] = time_dist.to_dict('records')
    # else:
    #     analysis_results['rto_flow_completion_time_distribution'] = []

    # # --- 6. Completion Time vs. RTO Count Correlation ---
    # df['completion_time_bucket'] = pd.cut(df['absolute_completion_time'], bins=10)
    # time_rto_corr = df.groupby('completion_time_bucket', observed=False)['rto_count'].mean().reset_index()
    # time_rto_corr.columns = ['completion_time_bucket', 'average_rto_count']
    # time_rto_corr['completion_time_bucket'] = time_rto_corr['completion_time_bucket'].astype(str)
    # analysis_results['completion_time_vs_rto_correlation'] = time_rto_corr.to_dict('records')

    return analysis_results

def main():
    parser = argparse.ArgumentParser(description='Parse FCT files to analyze RTO behavior and output JSON.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-rto") # New directory for RTO analysis JSONs
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    map_key_to_id = defaultdict(list)

    # --- History file parsing logic (from prase_dcn_fct.py) ---
    with open(history_filename, "r") as f:
        for line in f.readlines():
            # Assuming the same logic for finding relevant lines
            if "leaf_spine" in line or "leafspine" in line or "fat_k" in line:
                parsed = line.strip().split(',')
                if len(parsed) < 24: continue

                # Basic validation
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                if cc_mode_id not in cc_modes or lb_mode_id not in lb_modes:
                    continue

                key = (parsed[15], parsed[18], "Lossless" if int(parsed[10])==1 else "Lossy", parsed[17], parsed[19])
                entry_details = {
                    "config_id": parsed[1],
                    "lb_mode": lb_modes.get(lb_mode_id),
                    "cc_mode": cc_modes.get(cc_mode_id),
                    "recovery": irn_modes.get(int(parsed[11])), # Simplified for this script
                    "timeout_mode": parsed[21],
                    "window": parsed[14],
                    "rto_high": parsed[22],
                    "rto_low": parsed[23]
                }
                map_key_to_id[key].append(entry_details)

    # --- Process each group and generate JSON ---
    for k, v in map_key_to_id.items():
        group_data = {
            "metadata": {
                "topology": k[0],
                "network_load": k[1],
                "flow_control": k[2],
                "load_type": k[3],
                "error_rate": k[4],
            },
            "data_series": []
        }

        for entry in v:
            config_id = entry["config_id"]
            # Assuming the FCT file has a standard name and location
            fct_file = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
            
            if os.path.exists(fct_file):
                print(f"  Analyzing RTO data for config_id: {config_id}...")
                rto_analysis_result = analyze_rto_file(fct_file)
                
                if rto_analysis_result:
                    series_data = entry.copy() # Start with metadata from history
                    series_data["rto_analysis"] = rto_analysis_result
                    group_data["data_series"].append(series_data)
            else:
                print(f"  Skipping config_id {config_id}: FCT file not found at {fct_file}")

        if not group_data["data_series"]:
            print(f"Skipping group {k} due to no valid data.")
            continue
            
        json_filename = f"{json_dir}/RTO_ANALYSIS_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        
        print(f"Saving RTO analysis data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(group_data, f, indent=4)

if __name__ == "__main__":
    main()