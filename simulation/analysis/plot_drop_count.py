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
import re # 引入正則表達式模組

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
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=10)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 12
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def getFilePath():
    return os.path.dirname(os.path.abspath(__file__))

def parse_drop_stats(filename):
    """
    解析包含 Drop Statistics 的文件。
    """
    stats = {
        "TOR Drops": 0,
        "SPINE Drops": 0,
        "CORE Drops": 0
    }
    if not os.path.exists(filename):
        print(f"Warning: Drop stats file not found: {filename}")
        return stats

    with open(filename, 'r') as f:
        content = f.read()

        # 使用正則表達式提取數據，更穩健
        def get_total_drop(switch_type, text):
            # 匹配 "-> Up Total" 和 "-> Down Total" 並加總
            up_total_match = re.search(rf'\[{switch_type} Switches\].*?-> Up Total\s*:\s*(\d+)', text, re.DOTALL)
            down_total_match = re.search(rf'\[{switch_type} Switches\].*?-> Down Total\s*:\s*(\d+)', text, re.DOTALL)
            up_total = int(up_total_match.group(1)) if up_total_match else 0
            down_total = int(down_total_match.group(1)) if down_total_match else 0
            return up_total + down_total

        stats["TOR Drops"] = get_total_drop("ToR", content)
        stats["SPINE Drops"] = get_total_drop("Spine", content)
        
        # Core 交換機只有一個 Total
        core_total_match = re.search(r'\[Core Switches\].*?-> Total\s*:\s*(\d+)', content, re.DOTALL)
        stats["CORE Drops"] = int(core_total_match.group(1)) if core_total_match else 0

    return stats


def main():
    parser = argparse.ArgumentParser(description='Plotting Drop statistics of results')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to plot.')
    args = parser.parse_args()

    file_dir = getFilePath()
    fig_dir = os.path.join(file_dir, "figures_drop") # 建立新的資料夾存放 drop 圖表
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = os.path.join(os.path.dirname(file_dir), "mix", "output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

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
                    timeout_mode = parsed[21] # TMT-0 or TMT-1

                    if ar_mode != '0':
                        recovery_label = "AR-Go-Back-N"
                    else:
                        recovery_label = irn_modes.get(irn)

                    lb_mode_str = lb_modes.get(lb_mode_id)
                    flow_control = "Lossless" if pfc == 1 else "Lossy"
                    
                    short_topo = "LSS" if "leaf_spine" in topo else "FAT"
                    # 簡化標籤，只保留關鍵部分
                    plot_label = f"{lb_mode_str}+{recovery_label}"
                    
                    all_configs.append({
                        "config_id": config_id,
                        "label": plot_label,
                        "tmt": f"TMT-{timeout_mode}",
                        "algorithm": lb_mode_str
                    })
                    break

     # --- 數據處理 ---
    drop_results = []
    for config in all_configs:
        drop_stats_file = f"{output_dir}/{config['config_id']}/{config['config_id']}_out_flow_drop.txt"
        drop_data = parse_drop_stats(drop_stats_file)
        drop_results.append({**config, 'data': drop_data})

    # --- 繪圖 ---
    if drop_results:
        # *** 主要修改點：按照指定的順序排列 labels ***
        # 1. 定義您想要的順序
        lb_mode_order = ["fecmp", "letflow", "conga", "conweave", "drill", "rps", "adaptive"]
        
        # 2. 獲取數據中實際存在的演算法
        present_labels = set(res['algorithm'] for res in drop_results)
        
        # 3. 根據您的順序列表，篩選和排序存在的演算法
        labels = [algo for algo in lb_mode_order if algo in present_labels]

        tmt0_data = defaultdict(lambda: {'TOR Drops': 0, 'SPINE Drops': 0, 'CORE Drops': 0})
        tmt1_data = defaultdict(lambda: {'TOR Drops': 0, 'SPINE Drops': 0, 'CORE Drops': 0})

        for res in drop_results:
            if res['tmt'] == 'TMT-0':
                tmt0_data[res['algorithm']] = res['data']
            elif res['tmt'] == 'TMT-1':
                tmt1_data[res['algorithm']] = res['data']

        tmt0_tor = [tmt0_data[algo]['TOR Drops'] for algo in labels]
        tmt0_spine = [tmt0_data[algo]['SPINE Drops'] for algo in labels]
        tmt0_core = [tmt0_data[algo]['CORE Drops'] for algo in labels]

        tmt1_tor = [tmt1_data[algo]['TOR Drops'] for algo in labels]
        tmt1_spine = [tmt1_data[algo]['SPINE Drops'] for algo in labels]
        tmt1_core = [tmt1_data[algo]['CORE Drops'] for algo in labels]
        
        y = np.arange(len(labels))
        
        bar_height = 0.12 
        
        offsets = {
            'tmt0_tor': -2.5 * bar_height,
            'tmt0_spine': -1.5 * bar_height,
            'tmt0_core': -0.5 * bar_height,
            'tmt1_tor': 0.5 * bar_height,
            'tmt1_spine': 1.5 * bar_height,
            'tmt1_core': 2.5 * bar_height
        }
        
        colors = {
            'tmt0_tor': '#ff9999',  # Light Red
            'tmt0_spine': '#ff4d4d', # Medium Red
            'tmt0_core': '#b30000',  # Dark Red
            'tmt1_tor': '#a6cee3',  # Light Blue
            'tmt1_spine': '#1f78b4', # Medium Blue
            'tmt1_core': '#08306b'   # Dark Blue
        }
        
        fig, ax = plt.subplots(figsize=(16, 8))
        
        ax.barh(y + offsets['tmt0_tor'], tmt0_tor, bar_height, label='TOR Drops (TMT-0)', color=colors['tmt0_tor'])
        ax.barh(y + offsets['tmt0_spine'], tmt0_spine, bar_height, label='SPINE Drops (TMT-0)', color=colors['tmt0_spine'])
        ax.barh(y + offsets['tmt0_core'], tmt0_core, bar_height, label='CORE Drops (TMT-0)', color=colors['tmt0_core'])
        
        ax.barh(y + offsets['tmt1_tor'], tmt1_tor, bar_height, label='TOR Drops (TMT-1)', color=colors['tmt1_tor'])
        ax.barh(y + offsets['tmt1_spine'], tmt1_spine, bar_height, label='SPINE Drops (TMT-1)', color=colors['tmt1_spine'])
        ax.barh(y + offsets['tmt1_core'], tmt1_core, bar_height, label='CORE Drops (TMT-1)', color=colors['tmt1_core'])

        ax.set_xlabel('Total Packet Drops (Symmetric Log Scale)', fontsize=14)
        ax.set_ylabel('Load Balancing Algorithm', fontsize=14)
        ax.set_title('Packet Drop Summary by Source, Algorithm, and Timeout Mode', fontsize=16)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=12)
        
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=colors['tmt0_tor'], label='TOR Drops (TMT-0)'),
            Patch(facecolor=colors['tmt0_spine'], label='SPINE Drops (TMT-0)'),
            Patch(facecolor=colors['tmt0_core'], label='CORE Drops (TMT-0)'),
            Patch(facecolor=colors['tmt1_tor'], label='TOR Drops (TMT-1)'),
            Patch(facecolor=colors['tmt1_spine'], label='SPINE Drops (TMT-1)'),
            Patch(facecolor=colors['tmt1_core'], label='CORE Drops (TMT-1)'),
        ]
        ax.legend(handles=legend_elements, loc='upper right', fontsize=10, ncol=2)

        ax.xaxis.grid(True, linestyle='--', which='major', color='grey', alpha=0.6)
        ax.set_xscale("symlog")

        ax.invert_yaxis()
        plt.tight_layout()

        fig_filename = f"{fig_dir}/DROP_SUMMARY_CLUSTERED_ORDERED.pdf"
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()


if __name__ == "__main__":
    setup()
    main()