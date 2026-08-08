#!/usr/bin/python3

import subprocess
import os
import sys
import argparse
import matplotlib.pyplot as plt
from cycler import cycler
import math
import numpy as np

# LB/CC mode matching
cc_modes = {
    1: "dcqcn",
    3: "hp",
    7: "timely",
    8: "dctcp",
}
lb_modes = {
    0: "fecmp",
    1: "rps",
    2: "drill",
    3: "conga",
    6: "letflow",
    9: "conweave",
}
topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,
    "fat_k4_100G_OS2": 153000,
    "fat_k8_100G_OS1": 153000,
}

C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple',
    'xkcd:orange', 'xkcd:teal', 'xkcd:brick red',
    'xkcd:black', 'xkcd:brown', 'xkcd:grey',
]

LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D']

def read_cdf_file(file_path):
    x = []
    y = []
    with open(file_path, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            val = float(parts[0])
            cdf = float(parts[3])
            x.append(val)
            y.append(cdf)
    return x, y

def downsample_logspace(x, y, max_points=100):
    n = len(x)
    if n <= max_points:
        return x, y
    
    # x 是递增的，取对数空间等间距的点索引
    x = np.array(x)
    y = np.array(y)
    
    # 先计算对数范围，避免log(0)
    min_x = max(np.min(x), 1e-10)
    max_x = np.max(x)
    
    # 生成对数等间距的采样点
    sample_x = np.logspace(np.log10(min_x), np.log10(max_x), num=max_points)
    
    # 对每个采样点，在x中找最接近的点索引
    idx = np.searchsorted(x, sample_x, side='left')
    idx = np.clip(idx, 0, n-1)
    
    # 取对应点
    x_ds = x[idx].tolist()
    y_ds = y[idx].tolist()
    
    return x_ds, y_ds

def setup():
    def lcm(a, b):
        return abs(a*b) // math.gcd(a, b)

    def a(c1, c2):
        l = lcm(len(c1), len(c2))
        c1 = c1 * (l // len(c1))
        c2 = c2 * (l // len(c2))
        return c1 + c2

    def add(*cyclers):
        s = None
        for c in cyclers:
            s = c if s is None else a(s, c)
        return s

    plt.rc('axes', prop_cycle=(add(cycler(color=C),
                                   cycler(linestyle=LS),
                                   cycler(marker=M))))
    plt.rc('lines', markersize=5)
    plt.rc('legend', handlelength=3, handleheight=1.5, labelspacing=0.25)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def getFilePath():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    print("File directory: {}".format(dir_path))
    return dir_path

def main():
    parser = argparse.ArgumentParser(description='Plotting FCT of results')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end

    file_dir = getFilePath()
    fig_dir = os.path.join(file_dir, "figures")
    output_dir = os.path.join(file_dir, "../mix/output")
    history_filename = os.path.join(file_dir, "../mix/history_90_withAR.txt")

    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)

    map_key_to_id = {}
    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo in topo2bdp.keys():
                if topo in line:
                    parsed = line.strip().split(',')
                    config_id = parsed[1]
                    cc_mode = cc_modes[int(parsed[2])]
                    lb_mode = lb_modes[int(parsed[3])]
                    fc = (int(parsed[10]), int(parsed[11]))
                    flow_control = "IRN" if fc == (0, 1) else "Lossless" if fc == (1, 0) else None
                    if not flow_control:
                        continue
                    topo = parsed[14]
                    netload = parsed[17]
                    key = (topo, netload, flow_control)
                    map_key_to_id.setdefault(key, []).append([config_id, lb_mode])

    lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill"]

    for k, v in map_key_to_id.items():
        fig = plt.figure(figsize=(4, 4))
        ax = fig.add_subplot(111)
        fig.tight_layout()
        ax.set_xlabel("FCT Slowdown", fontsize=11.5)
        ax.set_ylabel("CDF", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')

        for tgt_lbmode in lbmode_order:
            for config_id, lb_mode in v:
                if lb_mode == tgt_lbmode:
                    cdf_file = os.path.join(output_dir, config_id, f"{config_id}_out_fct_large_slowdown_cdf.txt")
                    if not os.path.exists(cdf_file):
                        print(f"File not found: {cdf_file}")
                        continue
                    x, y = read_cdf_file(cdf_file)
                    x, y = downsample_logspace(x, y, max_points=20)  # 关键改动，控制点数量
                    print(f"Plotting {lb_mode} with {len(x)} points")
                    ax.plot(x, y, linewidth=2.0, label=lb_mode)

        ax.legend(bbox_to_anchor=(0.0, 1.2), loc="upper left", frameon=False, fontsize=12, ncol=2)
        ax.set_xscale("log")
        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)
        fig.tight_layout()

        fig_filename = os.path.join(fig_dir, f"CDF_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}.pdf")
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

if __name__ == "__main__":
    setup()
    main()
