#!/usr/bin/python3

import os
import sys
import argparse
import json
import pandas as pd
import matplotlib.pyplot as plt
from collections import defaultdict
from itertools import cycle

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -----------------------------------------

def getFilePath():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def analyze_throughput_file(file_path):
    """
    Analyzes a single throughput file.
    Returns:
        - A pandas Series of unacked bytes over time.
        - The final total of unacked bytes.
    """
    try:
        df = pd.read_csv(file_path, header=None, names=['time', 'hostId', 'accSendBytes', 'accAckedBytes'])
        if df.empty:
            return None, None, 0, 0
    except Exception:
        return None, None, 0, 0

    # --- Calculate Unacked Bytes over Time ---
    # Summing up send and acked bytes for all hosts at each timestamp
    time_grouped = df.groupby('time')
    unacked_series = time_grouped['accSendBytes'].sum() - time_grouped['accAckedBytes'].sum()
    unacked_series.name = "unacked_bytes"

    # --- Calculate Final Total Unacked Bytes ---
    # Get the last recorded state for each host to determine final totals
    df_last_state = df.sort_values('time').groupby('hostId').last()
    total_sent_bytes = df_last_state['accSendBytes'].sum()
    total_acked_bytes = df_last_state['accAckedBytes'].sum()
    final_total_unacked = total_sent_bytes - total_acked_bytes

    return unacked_series, final_total_unacked, total_sent_bytes, total_acked_bytes

def plot_data(csv_path):
    """
    Reads a CSV file and generates a plot, saving it to a file.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"  - ❗ Could not read CSV for plotting: {e}")
        return

    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(14, 8))

    # Create a cycle of line styles to use
    linestyles = cycle(['-', '--', '-.', ':'])

    # Skip the first column (assuming it is 'time' or index)
    for column in df.columns[1:]:
        linestyle = next(linestyles)
        ax.plot(df['time'], df[column], label=column, linewidth=2, linestyle=linestyle)

    ax.set_title('Unacknowledged Bytes Over Time', fontsize=18)
    ax.set_xlabel('Time (ns)', fontsize=12)
    ax.set_ylabel('Unacknowledged Bytes', fontsize=12)
    # Reduce legend font size slightly if there are many entries
    ax.legend(title='Experiment Runs', fontsize=9, loc='best')
    ax.grid(True)
    fig.tight_layout()

    plot_filename = os.path.splitext(csv_path)[0] + '.png'
    plt.savefig(plot_filename, dpi=300)
    plt.close(fig) # Close the figure to free up memory
    print(f"  - ✅ Plot saved to: {plot_filename}")

def main():
    parser = argparse.ArgumentParser(description='Analyze unacked bytes over time, generate CSV, and save plot.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    args = parser.parse_args()

    file_dir = getFilePath()
    csv_dir = os.path.join(file_dir, "csv-data-unacked")
    if not os.path.exists(csv_dir):
        os.makedirs(csv_dir)
    # Assuming output directory structure relative to script location
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    map_key_to_id = defaultdict(list)

    try:
        with open(history_filename, "r") as f:
            for line in f.readlines():
                if "leaf_spine" in line or "fat_k" in line:
                    parsed = line.strip().split(',')
                    if len(parsed) < 24: continue

                    try:
                        cc_mode_id = int(parsed[2])
                        lb_mode_id = int(parsed[3])
                    except ValueError:
                        continue

                    if cc_mode_id not in cc_modes or lb_mode_id not in lb_modes:
                        continue

                    # Key grouping: TOPO, LOAD, FC, TYPE, ERR, TIMEOUT_MODE
                    key = (parsed[15], parsed[18], "Lossless" if int(parsed[10])==1 else "Lossy", parsed[17], parsed[19], parsed[21])
                    entry_details = {
                        "config_id": parsed[1],
                        "lb_mode": lb_modes.get(lb_mode_id),
                        "cc_mode": cc_modes.get(cc_mode_id),
                        "timeout_mode": parsed[21],
                        "rto_high": parsed[22],
                        "rto_low": parsed[23]
                    }
                    map_key_to_id[key].append(entry_details)
    except FileNotFoundError:
        print(f"Error: History file not found at {history_filename}")
        return

    for k, v in map_key_to_id.items():
        print("\n" + "="*80)
        print(f"Processing Group: TOPO={k[0]}, LOAD={k[1]}, FC={k[2]}, TYPE={k[3]}, ERR={k[4]}, TM={k[5]}")
        print("="*80)

        all_time_series = []

        # --- FIX: Sort Descending (From Big to Small) based on RTO High then RTO Low ---
        # reverse=True means descending order
        v.sort(key=lambda s: (int(s.get('rto_high', 0)), int(s.get('rto_low', 0))), reverse=True)

        for entry in v:
            config_id = entry["config_id"]
            throughput_file = f"{output_dir}/{config_id}/{config_id}_out_throughput.txt"

            if os.path.exists(throughput_file):
                unacked_series, final_total_unacked, total_sent, total_acked = analyze_throughput_file(throughput_file)

                if unacked_series is not None:
                    timeout_mode_val = entry.get('timeout_mode', 'N/A')
                    loss_rate = (final_total_unacked / total_sent) * 100 if total_sent > 0 else 0
                    unacked_to_acked_ratio = (final_total_unacked / total_acked) * 100 if total_acked > 0 else 0

                    # --- FIX: Print both RTO High and Low ---
                    print(f"  - Config: {config_id} | RH: {entry['rto_high']} | RL: {entry['rto_low']} | TM: {timeout_mode_val} | "
                          f"Final Unacked: {int(final_total_unacked):,d} | "
                          f"Loss Rate: {loss_rate:.2f}% | "
                          f"Unacked/Acked: {unacked_to_acked_ratio:.2f}%")

                    # --- FIX: Label includes both High and Low RTOs ---
                    # RH = RTO High, RL = RTO Low
                    label = f"{entry['lb_mode']}_{entry['cc_mode']}_RH_{entry['rto_high']}_RL_{entry['rto_low']}_TM_{timeout_mode_val}"
                    unacked_series.name = label
                    all_time_series.append(unacked_series)
            else:
                pass

        if not all_time_series:
            print("Skipping group due to no valid data.")
            continue

        # Combine all series into one DataFrame
        combined_df = pd.concat(all_time_series, axis=1)

        # Handle missing timestamps
        combined_df.ffill(inplace=True)
        combined_df.bfill(inplace=True)
        combined_df.fillna(0, inplace=True)
        combined_df.sort_index(inplace=True)

        csv_filename = f"{csv_dir}/UNACKED_BYTES_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}_TM_{k[5]}.csv"

        combined_df.to_csv(csv_filename)
        print(f"\n  - ✅ CSV saved to: {csv_filename}")

        # Automatically plot the data from the generated CSV
        plot_data(csv_filename)

if __name__ == "__main__":
    main()
