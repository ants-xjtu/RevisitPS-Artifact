#!/usr/bin/python3

import pandas as pd
import argparse
import os
import json
from collections import defaultdict

# --- Dictionaries for mode mapping (Aligned with reference script) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
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

def analyze_pfc_log(filepath):
    """
    Parses a PFC log file and calculates key statistics, returning them as a dictionary.
    """
    try:
        column_names = ['TimeStep', 'NodeID', 'NodeType', 'IfIndex', 'PfcType']
        df = pd.read_csv(filepath, sep=' ', header=None, names=column_names)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print(f"Warning: PFC log file not found or is empty: {filepath}.")
        return None
    except Exception as e:
        print(f"Error reading or parsing file {filepath}: {e}")
        return None

    if df.empty:
        return {'total_duration_ns': 0, 'total_pause_count': 0, 'pause_frequency_per_ms': 0, 'simulation_time_ms': 0}

    total_pause_count = len(df[df['PfcType'] == 1])
    sim_start_time = df['TimeStep'].min()
    sim_end_time = df['TimeStep'].max()
    sim_duration_ns = sim_end_time - sim_start_time
    sim_duration_ms = sim_duration_ns / 1e6 if sim_duration_ns > 0 else 0

    df.sort_values(by='TimeStep', inplace=True)
    intervals = []
    grouped = df.groupby(['NodeID', 'IfIndex'])

    for (_, _), group_df in grouped:
        last_pause_start = None
        for _, row in group_df.iterrows():
            if row['PfcType'] == 1 and last_pause_start is None:
                last_pause_start = row['TimeStep']
            elif row['PfcType'] == 0 and last_pause_start is not None:
                intervals.append(row['TimeStep'] - last_pause_start)
                last_pause_start = None
        if last_pause_start is not None:
            intervals.append(sim_end_time - last_pause_start)

    total_pause_duration_ns = sum(intervals)
    pause_frequency = total_pause_count / sim_duration_ms if sim_duration_ms > 0 else 0

    # Return a dictionary with standard Python types to ensure JSON compatibility
    return {
        'total_duration_ns': int(total_pause_duration_ns),
        'total_pause_count': int(total_pause_count),
        'pause_frequency_per_ms': float(pause_frequency),
        'simulation_time_ms': float(sim_duration_ms)
    }

def main():
    parser = argparse.ArgumentParser(description='Parse PFC statistics and save to JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the history file containing simulation configurations.')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-pfc")
    os.makedirs(json_dir, exist_ok=True)
    # --- CHANGE: Standardized output directory path ---
    output_dir = os.path.join(file_dir, "../mix/output")
    
    print(f"Processing history file: {args.history_file}")

    map_key_to_config = defaultdict(list)

    # --- Step 1: Read history file and group configurations ---
    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue
                
                # --- CHANGE: Aligned parsing logic and variable names with reference ---
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])

                # Skip configs with modes not defined in the dictionaries
                if (cc_mode_id not in cc_modes or
                    lb_mode_id not in lb_modes or
                    irn not in irn_modes):
                    continue

                config_id = parsed[1]
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]

                # --- CHANGE: Replaced label derivation logic with reference implementation ---
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"
                
                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                
                # Group by these common parameters. Only Lossless configs are relevant for PFC.
                if flow_control == "Lossless":
                    key = (topo, netload, flow_control, load_type, error_rate)
                    entry_details = {
                        "config_id": config_id,
                        "lb_mode": lb_mode_str,
                        "recovery": recovery_label,
                    }
                    map_key_to_config[key].append(entry_details)

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")
                continue

    # --- Step 2: Process each group and generate a JSON file ---
    for k, v_configs in map_key_to_config.items():
        pfc_group_data = {
            "metadata": {
                "topology": k[0],
                "network_load": k[1],
                "flow_control": k[2],
                "load_type": k[3],
                "error_rate": k[4]
            },
            "data_series": []
        }

        for entry in v_configs:
            config_id = entry["config_id"]
            pfc_log_path = os.path.join(output_dir, config_id, f"{config_id}_out_pfc.txt")
            
            # print(f"---> Parsing PFC data for Config ID: {config_id}")
            stats = analyze_pfc_log(pfc_log_path)
            
            if stats is not None:
                series_data = {
                    "load_balancing_mode": entry["lb_mode"],
                    "recovery_mechanism": entry["recovery"],
                    "pfc_stats": stats
                }
                pfc_group_data["data_series"].append(series_data)
        
        if not pfc_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid PFC data.")
            continue
            
        # --- Step 3: Save the collected data to a JSON file ---
        json_filename = os.path.join(json_dir, f"PFC_DATA_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json")
        print(f"Saving PFC data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(pfc_group_data, f, indent=4)
            
    print("\n✅ All PFC files parsed successfully!")

if __name__ == "__main__":
    main()