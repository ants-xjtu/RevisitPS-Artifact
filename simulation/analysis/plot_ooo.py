#!/usr/bin/python3

import subprocess
import os
import sys
import argparse
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as tick
import math
from cycler import cycler
from collections import defaultdict
import numpy as np

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 4: "adaptive", 6: "letflow", 9: "conweave",
}
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN", #2: "DCP",
}
# -----------------------------------------

topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000, "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000, "leaf_spine_L16_S16_100G_OS1": 104000,
    "fat_k8_100G_OS2": 153000, "fat_k8_100G_OS1": 153000,
}
C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange',
    'xkcd:teal', 'xkcd:brick red', 'xkcd:black', 'xkcd:brown', 'xkcd:grey',
]
LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D']
H = ['//', 'o', '***', 'x', 'xxx']

def setup():
    def lcm(a, b): return abs(a*b) // math.gcd(a, b)
    def a(c1, c2):
        l = lcm(len(c1), len(c2)); c1 = c1 * (l // len(c1)); c2 = c2 * (l // len(c2)); return c1 + c2
    def add(*cyclers):
        s = None;
        for c in cyclers: s = c if s is None else a(s, c)
        return s
    plt.rc('axes', prop_cycle=(add(cycler(color=C), cycler(linestyle=LS), cycler(marker=M))))
    plt.rc('lines', markersize=5)
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=8) # 减小图例字号
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def getFilePath():
    return os.path.dirname(os.path.abspath(__file__))

def parse_ooo_stats(filename):
    stats = {
        "ooo_rate": 0.0,
        "reordering_distance": [],
        "burst_size": []
    }
    if not os.path.exists(filename):
        print(f"Warning: OOO stats file not found: {filename}")
        return stats

    dist_agg = defaultdict(int)
    burst_agg = defaultdict(int)

    current_section = None
    with open(filename, 'r') as f:
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
                try:
                    if current_section == 'overall':
                        parts = line.split(',')
                        if len(parts) == 3:
                            stats['ooo_rate'] = float(parts[2])
                    elif current_section == 'distance':
                        parts = line.split(',')
                        if len(parts) == 2:
                            original_val = int(parts[0])
                            count = int(parts[1])
                            transformed_val = math.ceil(original_val / 1000)
                            dist_agg[transformed_val] += count
                    elif current_section == 'burst':
                        parts = line.split(',')
                        if len(parts) == 2:
                            original_val = int(parts[0])
                            count = int(parts[1])
                            transformed_val = math.ceil(original_val / 1000)
                            burst_agg[transformed_val] += count
                except (ValueError, IndexError) as e:
                    print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")
    
    stats['reordering_distance'] = list(dist_agg.items())
    stats['burst_size'] = list(burst_agg.items())
    
    return stats

def calculate_cdf(data):
    if not data:
        return [], []
    
    data.sort(key=lambda x: x[0])
    
    values = [item[0] for item in data]
    counts = [item[1] for item in data]
    
    total_count = sum(counts)
    if total_count == 0:
        return [], []
        
    cumulative_counts = np.cumsum(counts)
    cdf_probs = cumulative_counts / total_count
    
    return [0] + values, [0] + list(cdf_probs)


def main():
    parser = argparse.ArgumentParser(description='Plotting OOO statistics of results')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to plot.')
    args = parser.parse_args()

    file_dir = getFilePath()
    fig_dir = os.path.join(file_dir, "figures_ooo")
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = os.path.join(os.path.dirname(file_dir), "mix", "output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    # 不再分组，使用一个列表存储所有配置
    all_configs = []

    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo_prefix in topo2bdp.keys():
                if topo_prefix in line:
                    parsed = line.strip().split(',')
                    if len(parsed) < 22: continue

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

                    if ar_mode != '0':
                        recovery_label = "AR-Go-Back-N"
                    else:
                        recovery_label = irn_modes.get(irn)

                    lb_mode_str = lb_modes.get(lb_mode_id)
                    flow_control = "Lossless" if pfc == 1 else "Lossy"
                    
                    # 创建一个包含所有信息的、更详细的图例
                    short_topo = "LSS" if "leaf_spine" in topo else "FAT"
                    plot_label = (f"{short_topo}+{netload}%+{lb_mode_str}+"
                                  f"{recovery_label}+TMT:{timeout_mode}+"
                                  f"Win:{window_size}+{flow_control}")
                    
                    all_configs.append([config_id, plot_label])
                    break

    lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill", "rps", "adaptive"]

    # --- 数据处理 ---
    # 循环所有配置，一次性获取所有数据
    ooo_results = []
    for config_id, full_label in all_configs:
        ooo_stats_file = f"{output_dir}/{config_id}/{config_id}_out_flow_drop.txt"
        ooo_data = parse_ooo_stats(ooo_stats_file)
        ooo_results.append({'label': full_label, 'data': ooo_data})

    # --- 绘图 ---
    # Plot 1: OOO Packet Rate (Bar Chart) - 只画一张
    if ooo_results:
        fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True) # 增加图表尺寸
        ax.set_ylabel("Out-of-Order Packet Rate", fontsize=11.5)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        
        labels = [res['label'] for res in ooo_results]
        rates = [res['data']['ooo_rate'] for res in ooo_results]

        if labels:
            bars = ax.bar(labels, rates)
            ax.bar_label(bars, fmt='%.4f', padding=3, fontsize=8)
            plt.setp(ax.get_xticklabels(), rotation=60, ha="right", rotation_mode="anchor") # 增加旋转角度
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            if max(rates, default=0) > 0:
                 ax.set_ylim(top=ax.get_ylim()[1] * 1.25)
            
            # 使用固定文件名
            fig_filename = f"{fig_dir}/OOO_RATE_ALL.pdf"
            print(f"Saving figure: {fig_filename}")
            plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

    # Plot 2: OOO Reordering Distance CDF - 只画一张
    if ooo_results:
        fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
        ax.set_xlabel("Reordering Distance (Packets)", fontsize=11.5)
        ax.set_ylabel("CDF", fontsize=11.5)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        
        plotted_something = False
        for res in ooo_results:
            dist_data = res['data']['reordering_distance']
            if dist_data:
                x_dist, y_cdf = calculate_cdf(dist_data)
                if x_dist:
                    ax.plot(x_dist, y_cdf, markersize=1.0, linewidth=2.0, label=res['label'])
                    plotted_something = True

        if plotted_something:
            ax.legend(bbox_to_anchor=(0.0, 1.02), loc="lower left", frameon=False, ncol=1)
            ax.set_xscale("log")
            ax.set_xlim(left=1)
            ax.set_ylim(0, 1.05)
            ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
            fig_filename = f"{fig_dir}/OOO_DIST_CDF_ALL.pdf"
            print(f"Saving figure: {fig_filename}")
            plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

    # Plot 3: OOO Burst Size CDF - 只画一张
    if ooo_results:
        fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
        ax.set_xlabel("OOO Burst Size (Packets)", fontsize=11.5)
        ax.set_ylabel("CDF", fontsize=11.5)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)

        plotted_something = False
        for res in ooo_results:
            burst_data = res['data']['burst_size']
            if burst_data:
                x_burst, y_cdf = calculate_cdf(burst_data)
                if x_burst:
                    ax.plot(x_burst, y_cdf, markersize=1.0, linewidth=2.0, label=res['label'])
                    plotted_something = True

        if plotted_something:
            ax.legend(bbox_to_anchor=(0.0, 1.02), loc="lower left", frameon=False, ncol=1)
            ax.set_xscale("log")
            ax.set_xlim(left=1)
            ax.set_ylim(0, 1.05)
            ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
            fig_filename = f"{fig_dir}/OOO_BURST_CDF_ALL.pdf"
            print(f"Saving figure: {fig_filename}")
            plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

if __name__ == "__main__":
    setup()
    main()