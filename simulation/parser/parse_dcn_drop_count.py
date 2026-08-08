#!/usr/bin/env python3

import os
import csv
import sys
import argparse
import json
import re
from collections import defaultdict

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -----------------------------------------

topo2bdp = {
    "leaf_spine_L2_S8_100G_OS1": 104000,
    "bigswitch_H16_100G_OS1": 104000,
    "leaf_spine_128_100G_OS2": 104000, "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000, "leaf_spine_L16_S16_100G_OS1": 104000,
    "leaf_spine_L8_S8_400G_OS2": 404000,
    "leaf_spine_L8_S16_400G_OS1": 404000,
    "fat_k8_100G_OS2": 153000, "fat_k8_100G_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_nofail_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_faill1_OS1": 153000, "three_layer_p4_tor4_l19_l28_s8_faill2_OS1":153000,
    "three_layer_p4_tor4_l19_l28_s8_faill12_OS1": 153000, "three_layer_p4_tor4_l19_l24_s8_faill23_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_failhalf_OS1": 153000,
    # Added Asymmetric Topologies
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1": 104000,
}

def getFilePath():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def safe_int(s, default=None):
    """Convert a string like '1' or '1,234' to int, return default on failure."""
    if s is None:
        return default
    try:
        return int(str(s).replace(',', '').strip())
    except Exception:
        return default

def parse_drop_stats(filename):
    """
    Parses a drop statistics file to extract counts from ToR, Spine, and Core switches.
    Returns a dict of counts.
    """
    stats = {
        "tor_drops_up": 0, "tor_drops_down": 0,
        "spine_drops_up": 0, "spine_drops_down": 0,
        "core_drops": 0, "total_drops": 0,
    }
    if not os.path.exists(filename):
        # Silence warning slightly or keep it for debug
        # print(f"Warning: Drop stats file not found: {filename}")
        return stats

    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    def sum_matches(pattern, text):
        found = re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        total = 0
        for m in found:
            try:
                total += int(m.replace(',', ''))
            except Exception:
                continue
        return total

    # Match any occurrence of "ToR ... Up Total : N" and sum all N
    up_pattern = r'ToR.*?Up\s*Total\s*[:=]\s*([0-9,]+)'
    down_pattern = r'ToR.*?Down\s*Total\s*[:=]\s*([0-9,]+)'
    stats["tor_drops_up"] = sum_matches(up_pattern, content)
    stats["tor_drops_down"] = sum_matches(down_pattern, content)

    up_pattern_spine = r'Spine.*?Up\s*Total\s*[:=]\s*([0-9,]+)'
    down_pattern_spine = r'Spine.*?Down\s*Total\s*[:=]\s*([0-9,]+)'
    stats["spine_drops_up"] = sum_matches(up_pattern_spine, content)
    stats["spine_drops_down"] = sum_matches(down_pattern_spine, content)

    # Core: sum all "Core ... Total : N"
    core_pattern = r'Core.*?Total\s*[:=]\s*([0-9,]+)'
    stats["core_drops"] = sum_matches(core_pattern, content)

    stats["total_drops"] = (
        stats["tor_drops_up"] + stats["tor_drops_down"] +
        stats["spine_drops_up"] + stats["spine_drops_down"] +
        stats["core_drops"]
    )
    return stats

def sanitize_filename_component(s):
    """Make a safe filename component."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(s))

def main():
    parser = argparse.ArgumentParser(description='Parse Drop Count results into JSON files.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    args = parser.parse_args()

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-drops")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    map_key_to_id = defaultdict(list)

    with open(history_filename, newline='', encoding='utf-8', errors='ignore') as csvfile:
        reader = csv.reader(csvfile)
        for rownum, parsed in enumerate(reader, start=1):
            if not parsed:
                continue
            line_text = ','.join(parsed)
            
            # Identify topology
            matched_topo = None
            for topo_prefix in topo2bdp.keys():
                if topo_prefix in line_text:
                    matched_topo = topo_prefix
                    break
            if not matched_topo:
                continue

            # --- CHANGE 1: Increase column check to 24 to include RTO cols ---
            if len(parsed) < 24:
                print(f"Warning: skipping row {rownum} (too few columns: {len(parsed)}). Need at least 24.")
                continue

            # Safe extraction of integer fields
            cc_mode_id = safe_int(parsed[2])
            lb_mode_id = safe_int(parsed[3])
            irn = safe_int(parsed[11])

            if cc_mode_id is None or lb_mode_id is None or irn is None:
                continue

            if (cc_mode_id not in cc_modes or
                lb_mode_id not in lb_modes or
                irn not in irn_modes):
                continue

            # Extract basic fields
            config_id = parsed[1].strip()
            ar_mode = parsed[4].strip()
            pfc = safe_int(parsed[10], default=0)
            topo = parsed[15].strip()
            load_type = parsed[17].strip()
            netload = parsed[18].strip()
            error_rate = parsed[19].strip()
            timeout_mode = parsed[21].strip()
            
            # --- CHANGE 2: Extract RTO High and Low ---
            rto_high = parsed[22].strip()
            rto_low = parsed[23].strip()

            # Compute recovery label
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

            lb_mode_str = lb_modes.get(lb_mode_id)
            flow_control = "Lossless" if pfc == 1 else "Lossy"
            
            # Grouping key
            key = (topo, netload, flow_control, load_type, error_rate)

            entry_details = {
                "config_id": config_id,
                "lb_mode": lb_mode_str,
                "cc_mode": cc_modes.get(cc_mode_id),
                "recovery": recovery_label,
                "timeout": timeout_mode,
                # --- CHANGE 3: Store RTO in details ---
                "rto_high": rto_high,
                "rto_low": rto_low
            }
            map_key_to_id[key].append(entry_details)

    # Process groups and write JSON files
    saved = 0
    for k, v in map_key_to_id.items():
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
            drop_stats_file = os.path.join(output_dir, config_id, f"{config_id}_out_flow_drop.txt")

            drop_data = parse_drop_stats(drop_stats_file)

            series_data = {
                "congestion_control_mode": entry.get("cc_mode"),
                "load_balancing_mode": entry.get("lb_mode"),
                "recovery_mechanism": entry.get("recovery"),
                "timeout_mode": entry.get("timeout"),
                # --- CHANGE 4: Write RTO to JSON ---
                "rto_high": entry.get("rto_high"),
                "rto_low": entry.get("rto_low"),
                "drop_counts": drop_data
            }
            plot_group_data["data_series"].append(series_data)

        if not plot_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid entries.")
            continue

        json_filename = os.path.join(
            json_dir,
            f"DROPS_TOPO_{sanitize_filename_component(k[0])}_LOAD_{sanitize_filename_component(k[1])}_FC_{sanitize_filename_component(k[2])}_TYPE_{sanitize_filename_component(k[3])}_ERR_{sanitize_filename_component(k[4])}.json"
        )

        try:
            print(f"Saving drop count data to: {json_filename}")
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(plot_group_data, f, indent=4)
            saved += 1
        except Exception as e:
            print(f"Error saving {json_filename}: {e}")

    print(f"Done. Saved {saved} JSON file(s).")

if __name__ == "__main__":
    main()