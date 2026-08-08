#!/usr/bin/python3
# Filename: parse_dcn_jct.py

import subprocess
import os
import sys
import argparse
import json
import numpy as np
from collections import defaultdict

# --- Dictionaries for mode mapping (consistent with provided scripts) ---
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

def get_file_path():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def get_ranked_jct_data(filename, time_start, time_end):
    """
    Processes a raw JCT data file to get average JCT for each group rank.
    The logic is modeled after the analysis in the provided JCT plotting script.

    Args:
        filename (str): Path to the raw JCT output file (e.g., '..._out_jct.txt').
        time_start (int): The start time (in ns) for filtering records.
        time_end (int): The end time (in ns) for filtering records.

    Returns:
        dict: A dictionary containing sorted ranks and their corresponding average JCTs in microseconds,
              or None if processing fails or yields no data.
    """
    # This awk command filters records by time and extracts the round ID ($1) and JCT in ns ($4)
    cmd_get_raw = f"cat {filename} | awk '{{ if ($3 > {time_start} && ($3 + $4) < {time_end}) print $1, $4}}'"
    jcts_by_round = defaultdict(list)
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip():
            print(f"Warning: No data returned from command for {filename}.")
            return None

        for line in output_raw.strip().split('\n'):
            parts = line.split()
            round_id = int(parts[0])
            jct_ns = float(parts[1])
            # Convert JCT from nanoseconds to microseconds
            jcts_by_round[round_id].append(jct_ns / 1000.0)

    except (subprocess.CalledProcessError, ValueError, IndexError) as e:
        print(f"Warning: Command or parsing failed for {filename}. Error: {e}. Returning None.")
        return None

    if not jcts_by_round:
        return None

    # Group JCTs by their rank within each round
    jcts_by_rank = defaultdict(list)
    for round_id, jct_list in jcts_by_round.items():
        sorted_jcts = sorted(jct_list)
        for rank, jct_value in enumerate(sorted_jcts):
            jcts_by_rank[rank].append(jct_value)

    # Calculate the average JCT for each rank across all rounds
    avg_jct_by_rank = {rank: np.mean(jct_values) for rank, jct_values in jcts_by_rank.items()}

    if not avg_jct_by_rank:
        return None

    sorted_ranks = sorted(avg_jct_by_rank.keys())
    avg_jcts = [avg_jct_by_rank[r] for r in sorted_ranks]

    return {"ranks": sorted_ranks, "avg_jcts_us": avg_jcts}

def main():
    """
    Main function to parse a history file, process corresponding JCT data,
    and save the aggregated results into JSON files.
    """
    parser = argparse.ArgumentParser(description='Parse JCT results into JSON files for plotting.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0, help='Start time in ns for filtering.')
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000, help='End time in ns for filtering.')
    args = parser.parse_args()

    file_dir = get_file_path()
    json_dir = os.path.join(file_dir, "json-data-jct")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    # A dictionary to group experiments by common parameters
    map_key_to_id = defaultdict(list)

    with open(history_filename, "r") as f:
        for line in f.readlines():
            if ',' not in line:
                continue
            
            parsed = line.strip().split(',')
            if len(parsed) < 22:
                continue

            try:
                # Parsing based on the format inferred from the provided plotting script
                config_id = parsed[1]
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                window_size = parsed[14]
                topo = parsed[15]
                load_type = parsed[17]
                message_size = parsed[18]
                error_rate = parsed[19]
                timeout_mode = parsed[21]

                # Skip configurations with undefined modes
                if (cc_mode_id not in cc_modes or
                    lb_mode_id not in lb_modes or
                    irn not in irn_modes):
                    continue

                # Determine human-readable labels for modes
                cc_label = cc_modes.get(cc_mode_id)
                lb_label = lb_modes.get(lb_mode_id)
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                        if irn in (0, 1):
                            recovery_label = "RTO+GBN"
                        elif irn == 2:
                            recovery_label = "IdealTrimming"
                    
                if timeout_mode == '1':
                    if recovery_label == "RTO+GBN":
                        recovery_label = "RTO+GBN+slowstart"
                    elif recovery_label == "IdealTrimming":
                        recovery_label = "IdealTrimming+slowstart"
                    elif recovery_label == "Ideal":
                        recovery_label = "Ideal+slowstart"

                flow_control = "Lossless" if pfc == 1 else "Lossy"
                
                # Define a key to group experiments that should be in the same JSON file
                key = (topo, load_type, error_rate, timeout_mode, flow_control)
                
                entry_details = {
                    "config_id": config_id,
                    "cc_mode": cc_label,
                    "lb_mode": lb_label,
                    "recovery": recovery_label,
                    "timeout": timeout_mode,
                    "window": window_size,
                    "message_size": message_size
                }
                map_key_to_id[key].append(entry_details)

            except (ValueError, IndexError) as e:
                print(f"Skipping malformed line in history file: {line.strip()} | Error: {e}")
                continue
    
    # Process each group of experiments and save to a separate JSON file
    for k, v in map_key_to_id.items():
        plot_group_data = {
            "metadata": {
                "topology": k[0],
                "load_type": k[1],
                "error_rate": k[2],
                "timeout_mode": k[3],
                "flow_control": k[4],
            },
            "data_series": []
        }

        for entry in v:
            config_id = entry["config_id"]
            jct_file = f"{output_dir}/{config_id}/{config_id}_out_jct.txt"
            
            if os.path.exists(jct_file):
                result = get_ranked_jct_data(jct_file, args.time_limit_begin, args.time_limit_end)
                
                if result:
                    series_data = {
                        "load_balancing_mode": entry["lb_mode"],
                        "congestion_control": entry["cc_mode"],
                        "recovery_mechanism": entry["recovery"],
                        "timeout_mode": entry["timeout"],
                        "window_size": entry["window"],
                        "message_size_bytes": int(entry["message_size"]),
                        "ranks": result["ranks"],
                        "avg_jct_us": result["avg_jcts_us"]
                    }
                    plot_group_data["data_series"].append(series_data)
    
        if not plot_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid JCT data.")
            continue
            
        # Construct a descriptive filename for the JSON output
        json_filename = f"{json_dir}/JCT_TOPO_{k[0]}_TYPE_{k[1]}_ERR_{k[2]}_TMT_{k[3]}_FC_{k[4]}.json"
        
        print(f"Saving data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(plot_group_data, f, indent=4)

if __name__ == "__main__":
    main()