#!/usr/bin/python3

import os
import sys
import argparse
import json
from collections import defaultdict, Counter
import numpy as np

# --- Dictionaries for mode mapping (consistent with FCT parser) ---
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

def calculate_cdf_points(data_list):
    """
    Calculates the CDF from a list of numbers and returns the points
    for plotting.
    """
    if not data_list:
        return {"values": [], "cdf": []}
    
    counts = Counter(data_list)
    # Sort items by value (e.g., number of incast flows)
    sorted_items = sorted(counts.items(), key=lambda x: x[0])
    
    values = [item[0] for item in sorted_items]
    value_counts = [item[1] for item in sorted_items]
    
    total_count = sum(value_counts)
    if total_count == 0:
        return {"values": [], "cdf": []}
        
    cumulative_counts = np.cumsum(value_counts)
    cdf_probs = cumulative_counts / total_count
    
    # Prepend a (0, 0) point to start the CDF plot from the origin
    return {"values": [0] + values, "cdf": [0.0] + list(cdf_probs)}

def parse_incast_log(filename):
    """
    Parses a raw drop incast log file (*_out_drop_incast.txt) and returns
    a dictionary of aggregated statistics.
    """
    if not os.path.exists(filename):
        print(f"Warning: Drop log file not found: {filename}")
        return None

    incast_flows = []
    incast_ips = []
    locations = []

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('DROP'):
                continue
            
            try:
                parts = line.split(',')
                if len(parts) >= 8:
                    # Construct location name, e.g., "TOR_0_0", "SPINE_1_2"
                    location_name = f"{parts[2]}_{parts[1]}_{parts[3]}"
                    incast_flow_count = int(parts[6])
                    incast_ip_count = int(parts[7])
                    
                    locations.append(location_name)
                    incast_flows.append(incast_flow_count)
                    incast_ips.append(incast_ip_count)
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")

    total_drops = len(locations)
    if total_drops == 0:
        return None # No data to report

    # --- Aggregate Statistics ---
    # 1. Count drops by switch type (TOR, SPINE, CORE)
    tor_drops = sum(1 for loc in locations if loc.startswith("TOR"))
    spine_drops = sum(1 for loc in locations if loc.startswith("SPINE"))
    core_drops = sum(1 for loc in locations if loc.startswith("CORE"))
    other_drops = total_drops - tor_drops - spine_drops - core_drops

    # 2. Count drops per exact location
    location_counts = Counter(locations)

    # 3. Calculate CDF data points for plotting
    flows_cdf = calculate_cdf_points(incast_flows)
    ips_cdf = calculate_cdf_points(incast_ips)

    result = {
        "total_drops": total_drops,
        "drops_by_type": {
            "tor": tor_drops,
            "spine": spine_drops,
            "core": core_drops,
            "other": other_drops
        },
        "drops_by_location": dict(sorted(location_counts.items(), key=lambda item: item[1], reverse=True)),
        "incast_flows_cdf": flows_cdf,
        "incast_ips_cdf": ips_cdf,
    }
    
    return result

def main():
    parser = argparse.ArgumentParser(description='Parse incast drop results into JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    args = parser.parse_args()

    file_dir = getFilePath()
    # Store output in a separate directory for clarity
    json_dir = os.path.join(file_dir, "json-data-incast")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    # Path to the simulation output directory
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    # Group configurations by key parameters (e.g., topology, load, etc.)
    map_key_to_id = defaultdict(list)

    with open(history_filename, "r") as f:
        for line in f.readlines():
            # This parsing logic is identical to the FCT parser to ensure consistency
            if "leaf_spine" in line or "fat_k" in line:
                parsed = line.strip().split(',')
                if len(parsed) < 22:
                    continue

                try:
                    cc_mode_id = int(parsed[2])
                    lb_mode_id = int(parsed[3])
                    irn = int(parsed[11])

                    if (cc_mode_id not in cc_modes or
                        lb_mode_id not in lb_modes or
                        irn not in irn_modes):
                        continue

                    config_id = parsed[1]
                    ar_mode = parsed[4]
                    pfc = int(parsed[10])
                    window_size = parsed[14]
                    topo = parsed[15]
                    load_type = parsed[17]
                    netload = parsed[18]
                    error_rate = parsed[19]
                    timeout_mode = parsed[21]
                except (ValueError, IndexError):
                    print(f"Warning: Skipping malformed line in history file: {line.strip()}")
                    continue
                
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1): recovery_label = "RTO+GBN"
                    elif irn == 2: recovery_label = "Ideal_Trimming"

                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                key = (topo, netload, flow_control, load_type, error_rate)
                
                entry_details = {
                    "config_id": config_id,
                    "lb_mode": lb_mode_str,
                    "recovery": recovery_label,
                    "timeout": timeout_mode,
                    "window": window_size
                }
                map_key_to_id[key].append(entry_details)

    # Process each group and generate a corresponding JSON file
    for k, v in map_key_to_id.items():
        # Define the main structure for the JSON output file
        plot_group_data = {
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
            incast_log_file = f"{output_dir}/{config_id}/{config_id}_out_drop_incast.txt"
            
            result = parse_incast_log(incast_log_file)
            
            if result:
                series_data = {
                    "load_balancing_mode": entry["lb_mode"],
                    "recovery_mechanism": entry["recovery"],
                    "timeout_mode": entry["timeout"],
                    "window_size": entry["window"],
                    "drop_stats": result
                }
                plot_group_data["data_series"].append(series_data)
    
        if not plot_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid drop data.")
            continue
            
        json_filename = f"{json_dir}/INCAST_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        
        print(f"Saving data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(plot_group_data, f, indent=4)

if __name__ == "__main__":
    main()