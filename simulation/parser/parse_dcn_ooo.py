#!/usr/bin/python3

import os
import sys
import argparse
import json
import math
from collections import defaultdict

# --- Dictionaries for mode mapping (consistent with provided scripts) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR",
    5: "WAdapt", 6: "LetFlow", 7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# --------------------------------------------------------------------

topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000, "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000, "leaf_spine_L16_S16_100G_OS1": 104000,
    "fat_k8_100G_OS2": 153000, "fat_k8_100G_OS1": 153000,
    "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1": 104000,
    "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1": 104000,
    "leafspine_L8_S16_100G_AsymFail10pct_OS1": 104000,
    "leafspine_L8_S16_100G_AsymFail1pct_OS1": 104000,
}

def getFilePath():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def parse_ooo_stats(filename):
    """
    Parses an OOO (Out-of-Order) statistics file.

    Args:
        filename (str): The path to the '_out_flow_drop.txt' file.

    Returns:
        dict: A dictionary containing the parsed OOO stats. Reordering distance
              is converted to packet counts (value/1000 and ceil).
              Returns an empty dict if the file doesn't exist or is empty.
    """
    stats = {
        "ooo_rate": 0.0,
        "reordering_distance_packets": [],
    }
    if not os.path.exists(filename):
        print(f"Warning: OOO stats file not found: {filename}")
        return {}

    dist_agg = defaultdict(int)

    try:
        with open(filename, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if not line:
                    continue

                if line.startswith('[OOO Overall Stats]'):
                    current_section = 'overall'
                elif line.startswith('[OOO Reordering Distance CDF]'):
                    current_section = 'distance'
                elif line.startswith('[OOO Burst Size CDF]'):
                    current_section = 'burst'
                elif line.startswith('[End Of Section]'):
                    current_section = None
                elif line.startswith('#') or line.startswith('='):
                    continue
                else:
                    parts = line.split(',')
                    if len(parts) < 2:
                        continue

                    if current_section == 'overall' and len(parts) == 3:
                        stats['ooo_rate'] = float(parts[2])
                    elif current_section == 'distance':
                        original_val = int(parts[0])
                        count = int(parts[1])
                        transformed_val = math.ceil(original_val / 1000)
                        dist_agg[transformed_val] += count
    except (ValueError, IndexError, IOError) as e:
        print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")
        return {}

    stats['reordering_distance_packets'] = sorted(dist_agg.items(), key=lambda x: x[0])

    return stats


def main():
    parser = argparse.ArgumentParser(description='Parse OOO statistics into JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-ooo-asy") # Separate directory for OOO data
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    map_key_to_config = defaultdict(list)

    # --- Step 1: Read history file and group configurations ---
    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo_prefix in topo2bdp.keys():
                if topo_prefix in line:
                    parsed = line.strip().split(',')
                    if len(parsed) < 22:
                        continue

                    cc_mode_id = int(parsed[2])
                    lb_mode_id = int(parsed[3])
                    irn = int(parsed[11])

                    # Filter based on modes defined in dictionaries
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
                    
                    # Determine recovery label
                    recovery_label = irn_modes.get(irn)
                    if ar_mode == '1':
                        if irn in (0, 1):
                            recovery_label = "RTO+GBN"
                        elif irn == 2:
                            recovery_label = "Ideal_Trimming"

                    lb_mode_str = lb_modes.get(lb_mode_id)
                    flow_control = "Lossless" if pfc == 1 else "Lossy"
                    
                    # Define a key to group similar experiments
                    key = (topo, netload, flow_control, load_type, error_rate)
                    
                    entry_details = {
                        "config_id": config_id,
                        "lb_mode": lb_mode_str,
                        "recovery": recovery_label,
                        "timeout": timeout_mode,
                        "window": window_size
                    }
                    map_key_to_config[key].append(entry_details)
                    break
    
    # --- Step 2: Process each group and generate a JSON file ---
    for k, v_configs in map_key_to_config.items():
        # This dictionary will be dumped to a single JSON file for the group
        ooo_group_data = {
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
            ooo_stats_file = f"{output_dir}/{config_id}/{config_id}_out_flow_drop.txt"

            result = parse_ooo_stats(ooo_stats_file)

            if result:
                series_data = {
                    "load_balancing_mode": entry["lb_mode"],
                    "recovery_mechanism": entry["recovery"],
                    "timeout_mode": entry["timeout"],
                    "window_size": entry["window"],
                    "ooo_packet_rate": result["ooo_rate"],
                    "reordering_distance_packets": result["reordering_distance_packets"],
                }
                ooo_group_data["data_series"].append(series_data)
    
        # If no valid data was found for any config in this group, skip creating the file
        if not ooo_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid OOO data.")
            continue
            
        # --- Step 3: Save the collected data to a JSON file ---
        json_filename = f"{json_dir}/OOO_DATA_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        
        print(f"Saving OOO data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(ooo_group_data, f, indent=4)

if __name__ == "__main__":
    main()
