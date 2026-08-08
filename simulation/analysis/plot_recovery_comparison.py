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

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 4: "adaptive", 6: "letflow", 9: "conweave",
}
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN", 2: "DCP",
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
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=9)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def getFilePath():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    return dir_path

def get_pctl(a, p):
    i = int(len(a) * p)
    if i >= len(a): i = len(a) - 1
    if i < 0: return 0
    return a[i]

def size2str(steps):
    result = []
    for step in steps:
        if step < 10000: result.append("{:.1f}K".format(step / 1000))
        elif step < 1000000: result.append("{:.0f}K".format(step / 1000))
        else: result.append("{:.1f}M".format(step / 1000000))
    return result

def get_steps_from_raw(filename, time_start, time_end, step=5):
    cmd_get_raw = f"cat {filename} | awk '{{ if ($6 > {time_start} && $6+$7 < {time_end}) {{ slow=$7/$8; print (slow<1?1:slow), $5}} }}'"
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip(): return {"avg": [], "p99": [], "size": []}
        raw_flows = [line.split() for line in output_raw.strip().split('\n')]
        raw_flows = [[float(f[0]), int(f[1])] for f in raw_flows if len(f) == 2]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"Warning: Command or parsing failed for {filename}. Returning empty result.")
        return {"avg": [], "p99": [], "size": []}
    flows_by_size = defaultdict(list)
    for slowdown, size in raw_flows: flows_by_size[size].append(slowdown)
    reordered_flows = []
    num_buckets = 100
    for size in sorted(flows_by_size.keys()):
        slowdowns_for_size = sorted(flows_by_size[size])
        n_flows = len(slowdowns_for_size)
        if n_flows == 0: continue
        buckets = [[] for _ in range(num_buckets)]
        for i, slowdown in enumerate(slowdowns_for_size): buckets[i % num_buckets].append(slowdown)
        for bucket in buckets:
            for slowdown in bucket: reordered_flows.append([slowdown, size])
    if not reordered_flows: return {"avg": [], "p99": [], "size": []}
    aa = [f"{slowdown} {size}" for slowdown, size in reordered_flows]
    nn = len(aa)
    res = [[i/100.] for i in range(0, 100, step)]
    for i in range(0, 100, step):
        l = int(i * nn / 100); r = int((i+step) * nn / 100)
        fct_size_chunk = aa[l:r]
        if not fct_size_chunk: res[int(i/step)].extend([0, 0, 0, 0, 0, 0]); continue
        fct_size_chunk = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size_chunk]
        fct = sorted(map(lambda x: x[0], fct_size_chunk))
        res[int(i/step)].append(fct_size_chunk[-1][1])
        res[int(i/step)].append(sum(fct) / len(fct))
        res[int(i/step)].append(get_pctl(fct, 0.5))
        res[int(i/step)].append(get_pctl(fct, 0.95))
        res[int(i/step)].append(get_pctl(fct, 0.99))
        res[int(i/step)].append(get_pctl(fct, 0.999))
    result = {"avg": [], "p99": [], "size": []}
    for item in res:
        if len(item) > 5:
            result["avg"].append(item[2]); result["p99"].append(item[5]); result["size"].append(item[1])
    return result

def main():
    parser = argparse.ArgumentParser(description='Plotting FCT comparison for recovery mechanisms.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to plot.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end
    STEP = 5

    file_dir = getFilePath()
    fig_dir = os.path.join(file_dir, "figures_recovery")
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = os.path.join(file_dir, "..", "mix", "output")

    history_filename = args.history_file
    print(f"Processing history file for recovery mechanism comparison: {history_filename}")

    map_key_to_id = defaultdict(list)

    with open(history_filename, "r") as f:
        for line in f.readlines():
            if ',' not in line: continue
            parsed = line.strip().split(',')
            if len(parsed) < 22: continue

            config_id = parsed[1]
            cc_mode_id = int(parsed[2])
            lb_mode_id = int(parsed[3])
            ar_mode = parsed[4]
            pfc = int(parsed[10])
            irn = int(parsed[11])
            window_size = parsed[14]
            topo = parsed[15]
            load_type = parsed[17]
            netload = parsed[18]
            error_rate = parsed[19]
            timeout_mode = parsed[21]
            
            if (cc_mode_id not in cc_modes or
                lb_mode_id not in lb_modes or
                irn not in irn_modes):
                continue
            
            recovery_label = "Unknown"
            if ar_mode != '0':
                recovery_label = "AR-Go-Back-N"
            else:
                recovery_label = irn_modes.get(irn, "Unknown")

            flow_control = "Lossless" if pfc == 1 else "Lossy"
            
            key = (topo, netload, flow_control, load_type, error_rate, window_size, timeout_mode, lb_mode_id)
            map_key_to_id[key].append([config_id, recovery_label])

    for k, v in map_key_to_id.items():
        if not v: continue
        
        x_tick_labels = []
        representative_config_id, _ = v[0]
        fct_slowdown_rep = os.path.join(output_dir, representative_config_id, f"{representative_config_id}_out_fct.txt")
        if os.path.exists(fct_slowdown_rep):
            representative_result = get_steps_from_raw(fct_slowdown_rep, time_start, time_end, STEP)
            if representative_result and representative_result["size"]:
                x_tick_labels = (['0'] + size2str(representative_result["size"]))[::2]
        xvals = [i for i in range(STEP, 100 + STEP, STEP)]
        
        # AVG plotting
        fig, ax = plt.subplots(figsize=(4.5, 4.5), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("Avg FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left'); ax.xaxis.set_ticks_position('bottom')
        
        for config_id, recovery_label in sorted(v, key=lambda x: x[1]):
            fct_slowdown = os.path.join(output_dir, config_id, f"{config_id}_out_fct.txt")
            if os.path.exists(fct_slowdown):
                result = get_steps_from_raw(fct_slowdown, time_start, time_end, STEP)
                if result and result["avg"]:
                    ax.plot(xvals, result["avg"], markersize=1.0, linewidth=3.0, label=recovery_label)

        ax.legend(title=f"LB Mode: {lb_modes[k[7]]}", bbox_to_anchor=(0.0, 1.02), loc="lower left", frameon=False, ncol=1)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        if x_tick_labels: ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
        fig_filename = f"{fig_dir}/AVG_RECOVERY_LB_{lb_modes[k[7]]}_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}_WIN_{k[5]}_TMT_{k[6]}.pdf"
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight'); plt.close()

        # P99 plotting
        fig, ax = plt.subplots(figsize=(4.5, 4.5), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("p99 FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left'); ax.xaxis.set_ticks_position('bottom')

        for config_id, recovery_label in sorted(v, key=lambda x: x[1]):
            fct_slowdown = os.path.join(output_dir, config_id, f"{config_id}_out_fct.txt")
            if os.path.exists(fct_slowdown):
                result = get_steps_from_raw(fct_slowdown, time_start, time_end, STEP)
                if result and result["p99"]:
                    ax.plot(xvals, result["p99"], markersize=1.0, linewidth=3.0, label=recovery_label)
        
        ax.legend(title=f"LB Mode: {lb_modes[k[7]]}", bbox_to_anchor=(0.0, 1.02), loc="lower left", frameon=False, ncol=1)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        if x_tick_labels: ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
        fig_filename = f"{fig_dir}/P99_RECOVERY_LB_{lb_modes[k[7]]}_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}_WIN_{k[5]}_TMT_{k[6]}.pdf"
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight'); plt.close()

if __name__ == "__main__":
    setup()
    main()