#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import argparse
import json
import re
from collections import Counter, defaultdict

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

def parse_raw_pfc_log(filename):
    """
    Parses a PFC incast log file, processing ONLY DOWNLINK events.
    Returns a dictionary containing lists of raw event data.
    """
    stats = {"locations": [], "incast_flows": [], "incast_ips": [], "queue_bytes": []}
    if not os.path.exists(filename):
        print(f"Warning: Raw PFC log file not found: {filename}")
        return stats
    
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('PFC'): continue
            try:
                parts = line.split(',')
                if len(parts) < 9: continue
                
                link_direction = parts[3]
                if link_direction != "DOWNLINK":
                    continue
                
                switch_type = parts[2]
                switch_id = parts[1]
                congested_port = parts[5]
                location_name = f"{switch_type}_{switch_id}_{congested_port}"
                
                stats["locations"].append(location_name)
                stats["queue_bytes"].append(int(parts[6]))
                stats["incast_flows"].append(int(parts[7]))
                stats["incast_ips"].append(int(parts[8]))
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")
    return stats

def main():
    parser = argparse.ArgumentParser(description='Parse DOWNLINK PFC incast events and save to JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the history file to process.')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-pfc-incast-workload") # New folder for clarity
    if not os.path.exists(json_dir): os.makedirs(json_dir)
    
    ns3_root_dir = os.path.abspath(os.path.join(file_dir, "..")) 
    output_dir = os.path.join(ns3_root_dir, "mix", "output")

    print(f"Processing history file: {args.history_file}")
    print("NOTE: Analysis is filtered to include DOWNLINK PFC events ONLY.")

    map_key_to_config = defaultdict(list)

    # --- Step 1: Read history file and group configurations ---
    with open(args.history_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue

                config_id = parsed[1]
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc_val = int(parsed[10])
                irn = int(parsed[11])
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]

                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"
                
                lb_mode_str = lb_modes.get(lb_mode_id, 'UnknownLB')
                flow_control = "Lossless" if pfc_val == 1 else "Lossy"
                
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
        incast_group_data = {
            "metadata": {
                "topology": k[0], "network_load": k[1], "flow_control": k[2],
                "load_type": k[3], "error_rate": k[4]
            },
            "data_series": []
        }

        for entry in v_configs:
            config_id = entry["config_id"]
            raw_log_file = os.path.join(output_dir, config_id, f"{config_id}_out_pfc_incast.txt")
            
            print(f"---> Parsing Incast PFC data for Config ID: {config_id}")
            pfc_data = parse_raw_pfc_log(raw_log_file)
            
            if not pfc_data['locations']:
                print(f"No DOWNLINK PFC event data found for config {config_id}.")
                continue
            
            # --- Perform Aggregation ---
            locations = pfc_data['locations']
            location_counts = Counter(locations)
            
            summary_stats = {
                "total_downlink_events": len(locations),
                "tor_event_count": sum(1 for loc in locations if loc.startswith("TOR")),
                "spine_event_count": sum(1 for loc in locations if loc.startswith("SPINE")),
                "core_event_count": sum(1 for loc in locations if loc.startswith("CORE")),
                "event_count_by_location": dict(location_counts)
            }

            # --- Prepare data for JSON ---
            series_data = {
                "load_balancing_mode": entry["lb_mode"],
                "recovery_mechanism": entry["recovery"],
                "summary": summary_stats,
                "raw_data_for_cdf": {
                    "incast_flows_per_event": pfc_data['incast_flows'],
                    "incast_ips_per_event": pfc_data['incast_ips'],
                    "queue_bytes_per_event": pfc_data['queue_bytes']
                }
            }
            incast_group_data["data_series"].append(series_data)
        
        if not incast_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid PFC incast data.")
            continue
            
        # --- Step 3: Save the collected data to a JSON file ---
        json_filename = os.path.join(json_dir, f"PFC_INCAST_DATA_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json")
        print(f"Saving PFC Incast data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(incast_group_data, f, indent=4)
            
    print("\n✅ All PFC Incast files parsed successfully!")

if __name__ == "__main__":
    main()