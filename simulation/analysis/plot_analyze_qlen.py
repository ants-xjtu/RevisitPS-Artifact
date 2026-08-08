#!/usr/bin/python3

import os
import argparse
import matplotlib.pyplot as plt
import math
from cycler import cycler
from collections import Counter, defaultdict
import numpy as np
import re

# --- Mode conversion dictionaries ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 4: "adaptive", 6: "letflow", 9: "conweave",
}
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN",
}
# ------------------------------------

C = ['xkcd:blue', 'xkcd:grass green', 'xkcd:red', 'xkcd:purple', 'xkcd:orange', 'xkcd:cyan', 'xkcd:magenta', 'xkcd:brown']
LS = ['solid', 'dashed', 'dotted', 'dashdot', 'solid', 'dashed', 'dotted', 'dashdot']

def setup():
    """Sets up the global Matplotlib styling."""
    plt.rc('axes', prop_cycle=(cycler(color=C) + cycler(linestyle=LS)))
    plt.rc('lines', linewidth=2.5)
    plt.rc('legend', handlelength=2.5, fontsize=11, frameon=False) # Reduced fontsize for potentially more legend items
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 14
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def get_file_path():
    """Returns the absolute path of the directory containing this script."""
    return os.path.dirname(os.path.abspath(__file__))

def parse_qlen_log(filename, leaf_ids, spine_ids):
    """
    Parses a queue length log file.
    File format: timestamp,node_id,port_id,ingress_qlen,dynamic_threshold,egress_qlen
    """
    data = {'leaf': {'ingress': [], 'egress': []}, 'spine': {'ingress': [], 'egress': []}}
    if not os.path.exists(filename):
        print(f"Warning: Queue log file not found: {filename}")
        return None

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                parts = line.split(',')
                if len(parts) != 6: continue
                node_id, ingress_qlen, egress_qlen = map(int, [parts[1], parts[3], parts[5]])
                
                if node_id in leaf_ids:
                    if ingress_qlen > 0:
                        data['leaf']['ingress'].append(ingress_qlen)
                    if egress_qlen > 0:
                        data['leaf']['egress'].append(egress_qlen)
                elif node_id in spine_ids:
                    if ingress_qlen > 0:
                        data['spine']['ingress'].append(ingress_qlen)
                    if egress_qlen > 0:
                        data['spine']['egress'].append(egress_qlen)
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")
    return data

def calculate_cdf(data_list):
    """Calculates the Cumulative Distribution Function (CDF) for a list of data."""
    if not data_list: return [], []
    counts = Counter(data_list)
    sorted_data = sorted(counts.items())
    values = [item[0] for item in sorted_data]
    value_counts = [item[1] for item in sorted_data]
    total_count = sum(value_counts)
    if total_count == 0: return [], []
    cumulative_counts = np.cumsum(value_counts)
    cdf_probs = cumulative_counts / total_count
    # Start CDF from 0
    return [0] + values, [0] + list(cdf_probs)

def main():
    parser = argparse.ArgumentParser(description='Analyze and plot comparative queue lengths from a history file.')
    parser.add_argument('history_file', type=str, help='Path to the history file to process.')
    args = parser.parse_args()

    script_dir = get_file_path()
    fig_dir = os.path.join(script_dir, "figures_qlen_comparative")
    if not os.path.exists(fig_dir): os.makedirs(fig_dir)
    
    ns3_root_dir = os.path.abspath(os.path.join(script_dir, "..")) 
    output_dir = os.path.join(ns3_root_dir, "mix", "output")

    # Define switch IDs
    leaf_switch_ids = set(range(128, 136))
    spine_switch_ids = set(range(136, 152))

    # --- STAGE 1: Collect and group all configuration data ---
    # The dictionary key will be a tuple (topology, netload, flow_control)
    # The value will be a list of dictionaries, each containing data for a specific configuration
    plot_groups = defaultdict(list)
    
    print(f"--- Stage 1: Reading history file and grouping configurations ---")
    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue
                
                config_id, topo, netload = parsed[1], parsed[15], parsed[18]
                cc_mode_id, lb_mode_id, ar_mode, pfc, irn, window_size, timeout_mode = map(
                    lambda i: parsed[i], [2, 3, 4, 10, 11, 14, 21]
                )
                
                if (int(cc_mode_id) not in cc_modes or int(lb_mode_id) not in lb_modes or int(irn) not in irn_modes):
                    continue
                
                # --- Define the Grouping Key and Legend Label ---
                short_topo = "LSS" if "leaf_spine" in topo else "FAT"
                flow_control = "Lossless" if int(pfc) == 1 else "Lossy"
                group_key = (short_topo, netload, flow_control)

                lb_mode_str = lb_modes.get(int(lb_mode_id))
                recovery_label = "AR-Go-Back-N" if ar_mode != '0' else irn_modes.get(int(irn))
                
                # This label will appear in the legend of the plot
                legend_label = f"{lb_mode_str}+{recovery_label}+TMT:{timeout_mode}+Win:{window_size}"

                # Find and parse the corresponding queue log file
                qlen_log_file = os.path.join(output_dir, config_id, f"{config_id}_out_qlen.txt")
                qlen_data = parse_qlen_log(qlen_log_file, leaf_switch_ids, spine_switch_ids)
                
                if qlen_data:
                    plot_groups[group_key].append({
                        'label': legend_label,
                        'data': qlen_data
                    })
                    print(f"  Added '{legend_label}' to group {group_key}")

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line: '{line}'. Error: {e}. Skipping.")

    # --- STAGE 2: Generate a set of comparative plots for each group ---
    print(f"\n--- Stage 2: Generating comparative plots ---")
    
    for group_key, configs_to_plot in plot_groups.items():
        short_topo, netload, flow_control = group_key
        print(f"\n---> Plotting Group: {short_topo} at {netload}% Load ({flow_control})")

        # Define the four plots to generate for this group
        plot_types = {
            'LEAF_INGRESS': ('leaf', 'ingress', "Ingress Queue CDF (Leaf Switches)"),
            'LEAF_EGRESS': ('leaf', 'egress', "Egress Queue CDF (Leaf Switches)"),
            'SPINE_INGRESS': ('spine', 'ingress', "Ingress Queue CDF (Spine Switches)"),
            'SPINE_EGRESS': ('spine', 'egress', "Egress Queue CDF (Spine Switches)"),
        }

        for name, (switch_type, q_type, title) in plot_types.items():
            fig, ax = plt.subplots(figsize=(8, 6), constrained_layout=True)
            
            has_data_to_plot = False
            for config in configs_to_plot:
                data = config['data'][switch_type][q_type]
                if not data:
                    print(f"  Warning: No data for '{config['label']}' in plot '{name}'. Skipping line.")
                    continue

                x, y = calculate_cdf(data)
                ax.plot(x, y, label=config['label'])
                has_data_to_plot = True

            if not has_data_to_plot:
                print(f"  Skipping plot '{name}' for group {group_key} as no data was found.")
                plt.close(fig)
                continue

            # --- Finalize and save the plot ---
            ax.set_title(f"{title}\n{short_topo} @ {netload}% Load ({flow_control})", fontsize=14)
            ax.set_xlabel("Queue Length (Bytes)")
            ax.set_ylabel("CDF")
            
            ax.grid(True, which='both', linestyle='--', linewidth=0.5)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.set_ylim(0, 1.05)
            # ax.set_xscale('log')
            ax.set_xlim(left=1) 
            ax.legend()

            filename_base = f"{short_topo}_{netload}p_{flow_control}"
            fig_filename = os.path.join(fig_dir, f"{filename_base}_QLEN_{name}_CDF.pdf")
            print(f"  Saving figure: {fig_filename}")
            plt.savefig(fig_filename, bbox_inches='tight')
            plt.close(fig)

if __name__ == "__main__":
    setup()
    main()