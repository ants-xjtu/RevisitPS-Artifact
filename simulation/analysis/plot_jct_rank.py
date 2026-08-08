#!/usr/bin/python3
# 檔名: plot_jct_rank_fixed_styles_v2.py (IRN/NGBN样式同步)

import subprocess
import os
import argparse
import matplotlib.pyplot as plt
import numpy as np
from cycler import cycler
from collections import defaultdict
import math

# --- Dictionaries & Styles (无变动) ---
lb_modes = {
    0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 4: "adaptive", 6: "letflow", 9: "conweave",
}
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN", 2: "DCP",
}
cc_modes = {
    1: "dcqcn",
    4: "none",
}
C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange', 'xkcd:teal',
    'xkcd:brick red', 'xkcd:black', 'xkcd:magenta', 'xkcd:brown', 'xkcd:sky blue',
    'xkcd:grey', 'xkcd:lime green', 'xkcd:gold', 'xkcd:royal blue', 'xkcd:pink'
]
LS = [
    'solid', 'dashed', 'dotted', 'dashdot',
    (0, (5, 5)), (0, (1, 1)), (0, (3, 5, 1, 5)), (0, (5, 10)), (0, (1, 10)),
    (0, (3, 10, 1, 10)), (5, (10, 3)), (0, (3, 1, 1, 1)), (0, (5, 1, 1, 1)),
    (0, (10, 5, 2, 5)), (0, (1, 5))
]
M = [
    'o', 's', 'x', 'v', 'D', '^', '<', '>',
    'p', 'P', '*', 'h', 'H', '+', '|'
]

# --- setup 和 get_ranked_jct_data 函数保持不变 ---
def setup():
    plt.rc('lines', markersize=6, linewidth=2.5)
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=9)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def get_ranked_jct_data(filename, time_start, time_end):
    cmd_get_raw = f"cat {filename} | awk '{{ if ($3 > {time_start} && ($3 + $4) < {time_end}) print $1, $4}}'"
    jcts_by_round = defaultdict(list)
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip(): return {}

        for line in output_raw.strip().split('\n'):
            parts = line.split()
            round_id = int(parts[0])
            jct_ns = float(parts[1])
            jcts_by_round[round_id].append(jct_ns / 1000.0)

    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"Warning: Command or parsing failed for {filename}. Returning empty dict.")
        return {}

    if not jcts_by_round:
        return {}

    jcts_by_rank = defaultdict(list)
    for round_id, jct_list in jcts_by_round.items():
        sorted_jcts = sorted(jct_list)
        for rank, jct_value in enumerate(sorted_jcts):
            jcts_by_rank[rank].append(jct_value)

    avg_jct_by_rank = {rank: np.mean(jct_values) for rank, jct_values in jcts_by_rank.items()}
    return avg_jct_by_rank

def main():
    parser = argparse.ArgumentParser(description='Plotting JCT vs. Group Rank with fixed styles.')
    parser.add_argument('history_files', nargs='+', type=str, help='A list of classified history files to aggregate and plot.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()
    setup()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "..", "mix", "output")
    fig_dir = os.path.join(script_dir, "figures_jct_rank_ascending")
    os.makedirs(fig_dir, exist_ok=True)

    aggregated_results = defaultdict(dict)
    workload_by_size = {} # --- NEW --- To store workload for each message size
    common_params_str = ""

    for history_filename in args.history_files:
        print(f"Processing {os.path.basename(history_filename)}...")
        with open(history_filename, "r") as f:
            for line in f.readlines():
                if ',' not in line: continue
                parsed = line.strip().split(',')
                if len(parsed) < 22: continue
                try:
                    # --- MODIFIED --- Added current_workload
                    config_id, cc_mode_id, lb_mode_id, ar_mode, irn, current_workload, message_size = \
                        parsed[1], int(parsed[2]), int(parsed[3]), parsed[4], int(parsed[11]), parsed[17], int(parsed[18])

                    if lb_mode_id not in lb_modes: continue

                    # --- NEW --- Store the workload for the message size
                    if message_size not in workload_by_size:
                        workload_by_size[message_size] = current_workload

                    cc_label = cc_modes.get(cc_mode_id, "UnknownCC")
                    lb_label = lb_modes.get(lb_mode_id, "UnknownLB")
                    recovery_label = "AR-Go-Back-N" if ar_mode != '0' else irn_modes.get(irn, "Unknown")
                    plot_label = f"{lb_label}+{cc_label}+{recovery_label}"
                    jct_file = os.path.join(output_dir, config_id, f"{config_id}_out_jct.txt")

                    if os.path.exists(jct_file):
                        avg_jct_by_rank = get_ranked_jct_data(jct_file, args.time_limit_begin, args.time_limit_end)
                        if avg_jct_by_rank:
                            sorted_ranks = sorted(avg_jct_by_rank.keys())
                            avg_jcts = [avg_jct_by_rank[r] for r in sorted_ranks]
                            aggregated_results[plot_label][message_size] = (sorted_ranks, avg_jcts)

                    if not common_params_str:
                        basename, _ = os.path.splitext(os.path.basename(history_filename))
                        parts = basename.split('_')
                        common_params_str = f"TOPO_{parts[1]}_WORKLOAD_{parts[3]}_ERR_{parts[4]}_TMT_{parts[5]}_FC_{parts[6]}_WIN_{parts[7]}"
                except (ValueError, IndexError):
                    continue

    if not aggregated_results:
        print("\nERROR: No valid data was aggregated. Plotting cancelled.")
        return

    all_message_sizes = set(size for data in aggregated_results.values() for size in data)
    if not all_message_sizes:
        print("\nERROR: No data points to plot. Exiting.")
        return

    # --- 绘图逻辑 ---
    ordered_labels = [
        "fecmp+dcqcn+N-Go-Back-N", "conga+dcqcn+N-Go-Back-N", "letflow+dcqcn+N-Go-Back-N",
        "conweave+dcqcn+N-Go-Back-N", "rps+dcqcn+AR-Go-Back-N", "drill+dcqcn+AR-Go-Back-N",
        "adaptive+dcqcn+AR-Go-Back-N", "rps+dcqcn+DCP", "drill+dcqcn+DCP",
        "adaptive+dcqcn+DCP", "rps+none+AR-Go-Back-N", "drill+none+AR-Go-Back-N",
        "adaptive+none+AR-Go-Back-N",
    ]
    fixed_style_map = {label: {'color': C[i], 'linestyle': LS[i], 'marker': M[i]}
                       for i, label in enumerate(ordered_labels)}

    for size in sorted(list(all_message_sizes)):
        print(f"Generating plot for message size: {size} Bytes...")
        fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
        ax.set_xlabel("Group Rank (0 = fastest)", fontsize=12)
        ax.set_ylabel("Average JCT (µs)", fontsize=12)
        ax.set_title(f"JCT vs. Rank for Message Size: {size} Bytes", fontsize=14)

        for base_label in ordered_labels:
            style = fixed_style_map.get(base_label)

            if base_label in aggregated_results and size in aggregated_results[base_label]:
                ranks, avg_jcts = aggregated_results[base_label][size]
                ax.plot(ranks, avg_jcts, label=base_label, **style)

            if "N-Go-Back-N" in base_label:
                irn_label = base_label.replace("N-Go-Back-N", "IRN")
                if irn_label in aggregated_results and size in aggregated_results[irn_label]:
                    ranks, avg_jcts = aggregated_results[irn_label][size]
                    ax.plot(ranks, avg_jcts, label=irn_label, **style)

        # --- NEW: Add optimal line ---
        if size == 19660800:
            workload = workload_by_size.get(size)
            
            # --- !!! 新增的除錯程式碼 !!! ---
            print("-----------------------------------------")
            print(f"DEBUG: Found message size {size}.")
            print(f"DEBUG: Parsed workload is: '{workload}'")
            # --- !!! 結束除錯程式碼 !!! ---

            optimal_jct_ns = 0
            if workload == "Alltoall":
                optimal_jct_ns = 11018048
            elif workload == "RingAllreduce":
                optimal_jct_ns = 22132096

            # --- !!! 新增的除錯程式碼 !!! ---
            print(f"DEBUG: Determined optimal JCT (ns): {optimal_jct_ns}")
            print("-----------------------------------------")
            # --- !!! 結束除錯程式碼 !!! ---

            if optimal_jct_ns > 0:
                optimal_jct_us = optimal_jct_ns / 1000.0
                ax.axhline(y=optimal_jct_us, color='red', linestyle=':', linewidth=2, label=f'Optimal {workload}')

        ax.legend(frameon=False)
        ax.grid(which='major', linestyle='--', alpha=0.6)
        ax.set_yscale("log")

        fig_filename = os.path.join(fig_dir, f"JCT_RANK_ASC_{common_params_str}_MSG_{size}.pdf")
        print(f"  -> Saving figure: {fig_filename}")
        fig.savefig(fig_filename, bbox_inches='tight')
        plt.close(fig)

if __name__ == "__main__":
    main()