#!/usr/bin/python3

import os
import argparse
import matplotlib.pyplot as plt
import math
from cycler import cycler
from collections import Counter
import numpy as np
import re

# --- 模式转换字典 ---
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

# --- (Matplotlib setup 和其他辅助函数保持不变) ---
C = ['xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange', 'xkcd:teal', 'xkcd:brick red', 'xkcd:black', 'xkcd:brown', 'xkcd:grey']
LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D']

def setup():
    def lcm(a, b): return abs(a*b) // math.gcd(a, b)
    def a(c1, c2):
        l = lcm(len(c1), len(c2)); c1 = c1 * (l // len(c1)); c2 = c2 * (l // len(c2)); return c1 + c2
    def add(*cyclers):
        s = None
        for c in cyclers: s = c if s is None else a(s, c)
        return s
    plt.rc('axes', prop_cycle=(add(cycler(color=C), cycler(linestyle=LS), cycler(marker=M))))
    plt.rc('lines', markersize=5)
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=8)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def getFilePath():
    return os.path.dirname(os.path.abspath(__file__))

def parse_raw_drop_log(filename):
    stats = {"locations": [], "incast_flows": [], "incast_ips": []}
    if not os.path.exists(filename):
        print(f"Warning: Raw drop log file not found: {filename}")
        return stats
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('DROP'): continue
            try:
                parts = line.split(',')
                if len(parts) >= 8:
                    # location_name is like "TOR_0_0", "SPINE_0_0", etc.
                    location_name = f"{parts[2]}_{parts[1]}_{parts[3]}" 
                    incast_flow_count = int(parts[6])
                    incast_ip_count = int(parts[7])
                    stats["locations"].append(location_name)
                    stats["incast_flows"].append(incast_flow_count)
                    stats["incast_ips"].append(incast_ip_count)
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse line in {filename}: '{line}'. Error: {e}")
    return stats

def calculate_cdf(data_list):
    if not data_list: return [], []
    counts = Counter(data_list)
    data = sorted(counts.items(), key=lambda x: x[0])
    values = [item[0] for item in data]
    value_counts = [item[1] for item in data]
    total_count = sum(value_counts)
    if total_count == 0: return [], []
    cumulative_counts = np.cumsum(value_counts)
    cdf_probs = cumulative_counts / total_count
    return [0] + values, [0] + list(cdf_probs)

def main():
    parser = argparse.ArgumentParser(description='Analyze incast drops using a history file.')
    parser.add_argument('history_file', type=str, help='Path to the history file to process.')
    args = parser.parse_args()

    file_dir = getFilePath()
    fig_dir = os.path.join(file_dir, "figures_incast")
    if not os.path.exists(fig_dir): os.makedirs(fig_dir)
    
    script_dir = getFilePath()
    ns3_root_dir = os.path.abspath(os.path.join(script_dir, "..")) 
    output_dir = os.path.join(ns3_root_dir, "mix", "output")

    print(f"Processing history file: {args.history_file}")
    
    # <<< MODIFICATION START 1 >>>
    # --- 全局统计变量 ---
    # summary_data 用于存储每个配置的结果，以便最后打印总结表格
    summary_data = []
    # grand_total_drops 用于累计所有配置的总丢包数
    grand_total_drops = 0
    # <<< MODIFICATION END 1 >>>

    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue

                config_id = parsed[1]
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                window_size = parsed[14]
                topo = parsed[15]
                netload = parsed[18]
                timeout_mode = parsed[21]

                if (cc_mode_id not in cc_modes or
                    lb_mode_id not in lb_modes or
                    irn not in irn_modes):
                    continue
                
                if ar_mode != '0':
                    recovery_label = "AR-Go-Back-N"
                else:
                    recovery_label = irn_modes.get(irn)
                
                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                short_topo = "LSS" if "leaf_spine" in topo else "FAT"

                plot_label = (f"{short_topo}+{netload}%+{lb_mode_str}+"
                              f"{recovery_label}+TMT:{timeout_mode}+"
                              f"Win:{window_size}+{flow_control}")
                
                plot_label = re.sub(r'[\\/*?:"<>|]',"-", plot_label)

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse label from line: '{line}'. Error: {e}. Skipping.")
                continue

            raw_log_file = os.path.join(output_dir, config_id, f"{config_id}_out_drop_incast.txt")
            
            print(f"\n---> Analyzing Config: {plot_label} ({config_id})")
            incast_data = parse_raw_drop_log(raw_log_file)
            
            locations = incast_data['locations']
            total_drops = len(locations)

            # <<< MODIFICATION START 2 >>>
            # --- 在循环中收集数据 ---
            # 统计不同类型交换机的丢包数量
            tor_drops = sum(1 for loc in locations if loc.startswith("TOR"))
            spine_drops = sum(1 for loc in locations if loc.startswith("SPINE"))
            core_drops = sum(1 for loc in locations if loc.startswith("CORE"))
            
            # 累加到总丢包数
            grand_total_drops += total_drops
            
            # 将当前配置的结果存入 summary_data 列表
            summary_data.append({
                "label": plot_label,
                "total": total_drops,
                "tor": tor_drops,
                "spine": spine_drops,
                "core": core_drops
            })
            # <<< MODIFICATION END 2 >>>
            
            if not locations:
                print("No drop data found for this config.")
                continue

            # --- 表格输出部分 ---
            location_counts = Counter(locations)
            print(f"--- Drop Location Analysis for: {plot_label} (Total Drops: {total_drops}) ---")

            sorted_locations = sorted(location_counts.items(), key=lambda item: item[1], reverse=True)
            print(f"{'Location':<25} | {'Drop Count':>15} | {'Percentage':>15}")
            print("-" * 62)
            for location, count in sorted_locations:
                percentage = (count / total_drops) * 100
                print(f"{location:<25} | {count:>15} | {f'{percentage:14.2f}%':>15}")

            # (画图部分保持不变)
            # 1. 生成 Incast Flows 图片
            fig1, ax1 = plt.subplots(figsize=(7, 5), constrained_layout=True)
            ax1.set_title(f"Incast Flow CDF for\n{plot_label}", fontsize=10)
            ax1.set_xlabel("Number of Incast Flows at Drop")
            ax1.set_ylabel("CDF")
            x_flows, y_cdf = calculate_cdf(incast_data['incast_flows'])
            if x_flows:
                ax1.plot(x_flows, y_cdf, linewidth=2.0)
            ax1.grid(True, which='both', linestyle='--', linewidth=0.5)
            ax1.set_ylim(0, 1.05)
            fig1_filename = os.path.join(fig_dir, f"{plot_label}_INCAST_FLOWS_CDF.pdf")
            print(f"Saving figure: {fig1_filename}")
            plt.savefig(fig1_filename, bbox_inches='tight')
            plt.close(fig1)

            # 2. 生成 Incast IPs 图片
            fig2, ax2 = plt.subplots(figsize=(7, 5), constrained_layout=True)
            ax2.set_title(f"Incast Source IP CDF for\n{plot_label}", fontsize=10)
            ax2.set_xlabel("Number of Incast Source IPs at Drop")
            ax2.set_ylabel("CDF")
            x_ips, y_cdf = calculate_cdf(incast_data['incast_ips'])
            if x_ips:
                ax2.plot(x_ips, y_cdf, linewidth=2.0)
            ax2.grid(True, which='both', linestyle='--', linewidth=0.5)
            ax2.set_ylim(0, 1.05)
            fig2_filename = os.path.join(fig_dir, f"{plot_label}_INCAST_IPS_CDF.pdf")
            print(f"Saving figure: {fig2_filename}")
            plt.savefig(fig2_filename, bbox_inches='tight')
            plt.close(fig2)

    # <<< MODIFICATION START 3 >>>
    # --- 脚本末尾打印最终总结表格 ---
    print("\n\n" + "="*140)
    print(" " * 55 + "--- FINAL DROP SUMMARY ---")
    print("="*140)

    if not summary_data:
        print("No data was processed to generate a summary.")
    else:
        # 打印表头
        print(f"{'Configuration Label':<80} | {'TOR Drops':>12} | {'SPINE Drops':>12} | {'CORE Drops':>12} | {'Total Drops':>15}")
        print("-" * 140)
        
        # 打印每一行的数据
        for item in summary_data:
            print(f"{item['label']:<80} | {item['tor']:>12} | {item['spine']:>12} | {item['core']:>12} | {item['total']:>15}")
        
        # 打印总计
        print("-" * 140)
        # 计算每列的总和
        total_tor = sum(item['tor'] for item in summary_data)
        total_spine = sum(item['spine'] for item in summary_data)
        total_core = sum(item['core'] for item in summary_data)
        print(f"{'GRAND TOTAL':<80} | {total_tor:>12} | {total_spine:>12} | {total_core:>12} | {grand_total_drops:>15}")
    
    print("="*140)
    # <<< MODIFICATION END 3 >>>


if __name__ == "__main__":
    setup()
    main()