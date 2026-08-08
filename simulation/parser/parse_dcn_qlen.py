#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandas as pd
import argparse
import os
import json
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
from itertools import cycle

def get_node_ids(n_leaf, n_spine, servers_per_leaf):
    """Calculates the node IDs for servers, leaves, and spines."""
    n_servers_total = n_leaf * servers_per_leaf
    server_ids = list(range(n_servers_total))
    
    id_offset_leaf = n_servers_total
    leaf_ids = list(range(id_offset_leaf, id_offset_leaf + n_leaf))
    
    id_offset_spine = id_offset_leaf + n_leaf
    spine_ids = list(range(id_offset_spine, id_offset_spine + n_spine))
    
    return server_ids, leaf_ids, spine_ids

def get_port_ranges(servers_per_leaf, n_spine):
    """Defines the port ID ranges for downlinks and uplinks on a leaf switch."""
    downlink_ports = list(range(servers_per_leaf))
    uplink_ports = list(range(servers_per_leaf, servers_per_leaf + n_spine))
    return downlink_ports, uplink_ports

def analyze_qlen_file(filepath, leaf_ids, spine_ids, downlink_ports, uplink_ports):
    """
    Reads a queue length data file, calculates average queue length over time,
    and extracts data for summary and CDF analysis in a specific time window.
    Returns a tuple: (time_series_df, summary_stats_dict, cdf_data_dict)
    """
    column_names = [
        'timestamp', 'node_id', 'port_id', 'ingress_qlen', 
        'dynamic_threshold', 'egress_qlen'
    ]
    try:
        # Read the original, unfiltered data
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            return None, None, None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None, None, None

    # --- Time Series Calculation (using all data) ---
    is_spine = df['node_id'].isin(spine_ids)
    is_leaf = df['node_id'].isin(leaf_ids)
    is_downlink_port = df['port_id'].isin(downlink_ports)
    is_uplink_port = df['port_id'].isin(uplink_ports)

    spine_df = df[is_spine]
    leaf_uplink_df = df[is_leaf & is_uplink_port]
    leaf_downlink_df = df[is_leaf & is_downlink_port]

    avg_spine_qlen = spine_df.groupby('timestamp')['egress_qlen'].mean().rename('avg_spine_qlen')
    avg_leaf_uplink_qlen = leaf_uplink_df.groupby('timestamp')['egress_qlen'].mean().rename('avg_leaf_uplink_qlen')
    avg_leaf_downlink_qlen = leaf_downlink_df.groupby('timestamp')['egress_qlen'].mean().rename('avg_leaf_downlink_qlen')

    combined_df = pd.concat([avg_spine_qlen, avg_leaf_uplink_qlen, avg_leaf_downlink_qlen], axis=1)
    combined_df.ffill(inplace=True)
    combined_df.bfill(inplace=True)
    combined_df.fillna(0, inplace=True)
    
    # --- Stats for 2s - 2.05s window (using all data) ---
    start_ns = 2_000_000_000
    end_ns = 2_060_000_000
    
    # Filter the main time-series dataframe to the specified window
    combined_df = combined_df.reset_index()
    time_series_in_window = combined_df[(combined_df['timestamp'] >= start_ns) & (combined_df['timestamp'] <= end_ns)]

    summary_stats = {}
    cdf_data = {}
    percentiles_to_calc = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99]

    # Note: We use the original spine_df, leaf_uplink_df, etc. for these stats
    for name, category_df in [('spine', spine_df), ('leaf_uplink', leaf_uplink_df), ('leaf_downlink', leaf_downlink_df)]:
        df_in_range = category_df[(category_df['timestamp'] >= start_ns) & (category_df['timestamp'] <= end_ns)]
        
        summary_stats[name] = {} # Make it a nested dictionary for better organization
        
        if not df_in_range.empty:
            qlen_data = df_in_range['egress_qlen']
            summary_stats[name]['avg'] = qlen_data.mean()
            summary_stats[name]['max'] = qlen_data.max()
            for p in percentiles_to_calc:
                summary_stats[name][f'p{int(p*100)}'] = qlen_data.quantile(p)
        else:
            summary_stats[name]['avg'] = 0
            summary_stats[name]['max'] = 0
            for p in percentiles_to_calc:
                summary_stats[name][f'p{int(p*100)}'] = 0
        
        cdf_data[name] = df_in_range['egress_qlen'].tolist()

    return time_series_in_window, summary_stats, cdf_data

def plot_qlen_data(csv_path):
    """Reads a CSV with queue length data and saves a plot."""
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"  - ❗ Could not read CSV for plotting: {e}")
        return

    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(14, 8))
    linestyles = cycle(['-', '--', '-.'])

    for column in df.columns[1:]: # Skip the 'timestamp' column
        linestyle = next(linestyles)
        ax.plot(df['timestamp'], df[column], label=column, linewidth=2, linestyle=linestyle)

    ax.set_title('Average Egress Queue Length Over Time', fontsize=18)
    ax.set_xlabel('Time (ns)', fontsize=12)
    ax.set_ylabel('Average Queue Length (Bytes)', fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True)
    fig.tight_layout()

    plot_filename = os.path.splitext(csv_path)[0] + '.png'
    plt.savefig(plot_filename, dpi=300)
    plt.close(fig)
    print(f"  - ✅ Plot saved to: {plot_filename}")

def plot_cdf_data(cdf_data, base_filename):
    """Takes a dictionary of raw queue length data and plots a CDF."""
    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(14, 8))
    linestyles = cycle(['-', '--', '-.'])

    for name, data in cdf_data.items():
        if not data:
            continue
        
        sorted_data = np.sort(data)
        yvals = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        
        linestyle = next(linestyles)
        ax.plot(sorted_data, yvals, label=name, linewidth=2, linestyle=linestyle)

    ax.set_title('CDF of Egress Queue Length (2s - 2.05s)', fontsize=18)
    ax.set_xlabel('Egress Queue Length (Bytes)', fontsize=12)
    ax.set_ylabel('Cumulative Probability', fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True)
    fig.tight_layout()

    plot_filename = os.path.splitext(base_filename)[0] + '_cdf.png'
    plt.savefig(plot_filename, dpi=300)
    plt.close(fig)
    print(f"  - ✅ CDF Plot saved to: {plot_filename}")

def plot_individual_port_qlen(filepath, config_id, output_dir):
    """
    Plots the qlen for each individual active port after 2.06s.
    """
    column_names = ['timestamp', 'node_id', 'port_id', 'ingress_qlen', 'dynamic_threshold', 'egress_qlen']
    try:
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            return
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return

    cutoff_ns = 2_060_000_000
    df_after_cutoff = df[df['timestamp'] > cutoff_ns]

    if df_after_cutoff.empty:
        print("  - ℹ️ No queue data found after 2.06s to plot for individual ports.")
        return

    # Filter to get only ports that had a non-zero queue in this window
    active_ports_df = df_after_cutoff.groupby(['node_id', 'port_id']).filter(lambda x: x['egress_qlen'].sum() > 0)

    if active_ports_df.empty:
        print("  - ℹ️ All ports had zero queue length after 2.06s. No plot generated.")
        return

    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(16, 9))

    # Plot each active port
    for (node, port), data in active_ports_df.groupby(['node_id', 'port_id']):
        ax.plot(data['timestamp'], data['egress_qlen'], label=f'Node {node}-Port {port}', linewidth=1, alpha=0.8)

    ax.set_title(f'Individual Port Egress Queue Length After 2.06s (Config: {config_id})', fontsize=18)
    ax.set_xlabel('Time (ns)', fontsize=12)
    ax.set_ylabel('Egress Queue Length (Bytes)', fontsize=12)
    
    # Only show legend if there are a reasonable number of lines
    if len(active_ports_df.groupby(['node_id', 'port_id'])) < 15:
        ax.legend(fontsize=8)
        
    ax.grid(True)
    fig.tight_layout()

    plot_filename = os.path.join(output_dir, f"INDIVIDUAL_QLEN_{config_id}.png")
    plt.savefig(plot_filename, dpi=300)
    plt.close(fig)
    print(f"  - ✅ Individual Port Plot saved to: {plot_filename}")


def main():
    parser = argparse.ArgumentParser(description='Analyze and plot average queue lengths for spine, leaf uplinks, and leaf downlinks.')
    parser.add_argument('history_file', type=str, help='Path to the history file.')
    parser.add_argument('--n_leaf', type=int, default=8, help='Number of leaf switches.')
    parser.add_argument('--n_spine', type=int, default=16, help='Number of spine switches.')
    parser.add_argument('--servers_per_leaf', type=int, default=16, help='Number of servers per leaf.')
    args = parser.parse_args()

    file_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(file_dir, "csv-data-qlen")
    if not os.path.exists(csv_dir):
        os.makedirs(csv_dir)
    
    ns3_root_dir = os.path.abspath(os.path.join(file_dir, "..")) 
    output_data_dir = os.path.join(ns3_root_dir, "mix", "output")
    
    print(f"Processing history file: {args.history_file}")
    
    _, leaf_ids, spine_ids = get_node_ids(args.n_leaf, args.n_spine, args.servers_per_leaf)
    downlink_ports, uplink_ports = get_port_ranges(args.servers_per_leaf, args.n_spine)
    print(f"Identified Leaf IDs: {leaf_ids}")
    print(f"Identified Spine IDs: {spine_ids}")
    print(f"Identified Leaf Downlink Ports: {downlink_ports}")
    print(f"Identified Leaf Uplink Ports: {uplink_ports}")

    config_details_map = {}
    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 24: continue
                
                config_id = parsed[1]
                rto_high = parsed[22]
                rto_low = parsed[23]
                timeout_mode = parsed[21]

                config_details_map[config_id] = {
                    "rto_high": rto_high,
                    "rto_low": rto_low,
                    "timeout_mode": timeout_mode
                }
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")
                continue

    for config_id, details in config_details_map.items():
        print("\n" + "="*80)
        print(f"Processing Config ID: {config_id} | RTO: {details['rto_high']}/{details['rto_low']} | Timeout Mode: {details['timeout_mode']}")
        print("="*80)

        qlen_file_path = os.path.join(output_data_dir, config_id, f"{config_id}_out_qlen.txt")
        
        # --- Run original analyses ---
        qlen_df, summary_stats, cdf_data = analyze_qlen_file(qlen_file_path, leaf_ids, spine_ids, downlink_ports, uplink_ports)

        if qlen_df is not None and not qlen_df.empty:
            csv_filename = os.path.join(csv_dir, f"AVG_QLEN_{config_id}.csv")
            qlen_df.to_csv(csv_filename, index=False)
            print(f"  - ✅ CSV saved to: {csv_filename}")
            
            plot_qlen_data(csv_filename)
            plot_cdf_data(cdf_data, csv_filename)

            print("\n  --- QLen Stats (2s - 2.05s) ---")
            percentiles_to_print = [50, 60, 70, 80, 90, 95, 99]
            for category in ['spine', 'leaf_uplink', 'leaf_downlink']:
                stats = summary_stats[category]
                print(f"  - {category.replace('_', ' ').title()}:")
                print(f"    Avg: {stats['avg']:.2f} Bytes")
                print(f"    Max: {stats['max']:.2f} Bytes")
                for p in percentiles_to_print:
                    print(f"    P{p}: {stats[f'p{p}']:.2f} Bytes")
            print("  -----------------------------------")
        else:
            print(f"  - ❗ No queue length data found or processed for Config ID: {config_id}")

        # --- Run new, separate analysis for individual port plotting ---
        plot_individual_port_qlen(qlen_file_path, config_id, csv_dir)

    print("\n✅ All configurations processed!")

if __name__ == "__main__":
    main()
