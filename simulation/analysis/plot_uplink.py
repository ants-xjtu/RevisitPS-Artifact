#!/usr/bin/python3

import subprocess
import os
import sys
import argparse
import matplotlib.pyplot as plt
import numpy as np
import math
from cycler import cycler

# ---------------- Constants ------------------
cc_modes = {1: "dcqcn", 3: "hp", 7: "timely", 8: "dctcp"}
lb_modes = {0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 6: "letflow", 9: "conweave"}
topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,
    "fat_k4_100G_OS2": 153000,
    "fat_k8_100G_OS1": 153000,
}

C = ['xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange', 'xkcd:teal']
LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D']


# ---------------- Utils ------------------
def getCdfFromArray(data_arr):
    v_sorted = np.sort(data_arr)
    p = 1. * np.arange(len(data_arr)) / (len(data_arr) - 1)
    od = []
    bkt = [0, 0, 0, 0]
    n_accum = 0
    for i in range(len(v_sorted)):
        key = v_sorted[i]
        n_accum += 1
        if bkt[0] == key:
            bkt[1] += 1
            bkt[2] = n_accum
            bkt[3] = p[i]
        else:
            od.append(bkt)
            bkt = [0, 0, 0, 0]
            bkt[0] = key
            bkt[1] = 1
            bkt[2] = n_accum
            bkt[3] = p[i]
    if od[-1][0] != bkt[0]:
        od.append(bkt)
    od.pop(0)
    return od


def setup():
    def lcm(a, b):
        return abs(a * b) // math.gcd(a, b)

    def a(c1, c2):
        l = lcm(len(c1), len(c2))
        return c1 * (l // len(c1)) + c2 * (l // len(c2))

    def add(*cyclers):
        s = None
        for c in cyclers:
            if s is None:
                s = c
            else:
                s = a(s, c)
        return s

    plt.rc('axes', prop_cycle=(add(cycler(color=C), cycler(linestyle=LS), cycler(marker=M))))
    plt.rc('lines', markersize=5)
    plt.rc('legend', handlelength=3, handleheight=1.5, labelspacing=0.25)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42


def getFilePath():
    return os.path.dirname(os.path.realpath(__file__))


# ---------------- Metric Calculation ------------------
def compute_metric(vec, metric):
    if np.mean(vec) == 0:
        return None
    if metric == "cv":
        return np.std(vec) / np.mean(vec) * 100
    elif metric == "range":
        return (np.max(vec) - np.min(vec)) / np.mean(vec) * 100
    elif metric == "jain":
        numerator = (np.sum(vec))**2
        denominator = len(vec) * np.sum(np.square(vec))
        if denominator == 0:
            return None
        return (1 - numerator / denominator) * 100  # convert to "unfairness"
    else:
        raise ValueError("Unknown metric: " + metric)


# ---------------- Main ------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=2005000000)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=2100000000)
    parser.add_argument('--metric', choices=['cv', 'range', 'jain'], default='cv',
                        help="Metric to use in imbalance mode: cv, range, jain")
    parser.add_argument('--mode', choices=['imbalance', 'throughput'], default='imbalance',
                        help="Plot mode: imbalance (default) or throughput")
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end
    time_interval = 100000

    metric_type = args.metric
    mode = args.mode

    file_dir = getFilePath()
    fig_dir = file_dir + "/figures"
    output_dir = file_dir + "/../mix/output"
    history_filename = file_dir + "/../mix/history_90_withAR.txt"

    map_key_to_id = {}
    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo in topo2bdp.keys():
                if topo in line:
                    parsed_line = line.strip().split(',')
                    config_id = parsed_line[1]
                    cc_mode = cc_modes[int(parsed_line[2])]
                    lb_mode = lb_modes[int(parsed_line[3])]
                    fc = (int(parsed_line[10]), int(parsed_line[11]))
                    if fc == (0, 1):
                        flow_control = "IRN"
                    elif fc == (1, 0):
                        flow_control = "Lossless"
                    else:
                        continue
                    topo = parsed_line[14]
                    netload = parsed_line[17]
                    key = (topo, netload, flow_control)
                    map_key_to_id.setdefault(key, []).append([config_id, lb_mode])

    for k, v in map_key_to_id.items():
        fig = plt.figure(figsize=(5, 3))
        ax = fig.add_subplot(111)
        fig.tight_layout()

        if mode == "imbalance":
            ax.set_xlabel(f"Uplink Imbalance ({metric_type.upper()}) [%]", fontsize=11.5)
        else:
            ax.set_xlabel("Avg Port Throughput [Gbps]", fontsize=11.5)

        ax.set_ylabel("CDF", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')

        lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill"]
        for tgt_lbmode in lbmode_order:
            for vv in v:
                config_id, lb_mode = vv
                if lb_mode != tgt_lbmode:
                    continue
                filename_uplink = f"{output_dir}/{config_id}/{config_id}_out_uplink.txt"

                port_bytes = {}  # key: (swid, portid) → list of bytes
                ts_first, ts_last = None, None

                with open(filename_uplink, "r") as f:
                    last_val = {}
                    for line in f:
                        ts, swid, portid, val = map(int, line.strip().split(','))
                        if not (time_start <= ts <= time_end):
                            continue
                        key = (swid, portid)
                        if key not in last_val:
                            last_val[key] = (ts, val)
                        else:
                            prev_ts, prev_val = last_val[key]
                            if ts - prev_ts >= time_interval:
                                delta = val - prev_val
                                port_bytes.setdefault(key, []).append(delta)
                                last_val[key] = (ts, val)

                            ts_first = min(ts_first, ts) if ts_first else ts
                            ts_last = max(ts_last, ts) if ts_last else ts

                if mode == "imbalance":
                    switch_diff_data = {}
                    for (swid, portid), vals in port_bytes.items():
                        switch_diff_data.setdefault(swid, []).append(vals)

                    ts_data_arr = []
                    for swid, vecs in switch_diff_data.items():
                        vecs_T = np.array(vecs).T.tolist()
                        for vec in vecs_T:
                            result = compute_metric(vec, metric_type)
                            if result is not None:
                                ts_data_arr.append(result)

                    cdf_arr = getCdfFromArray(ts_data_arr)
                    ax.set_xlim(0, 200)
                    ax.plot([x[0] for x in cdf_arr],
                            [x[3] for x in cdf_arr],
                            markersize=0,
                            linewidth=3.0,
                            label=lb_mode)
                else:
                    # Throughput mode
                    avg_throughputs = []
                    duration = (ts_last - ts_first) / 1e9  # seconds
                    for key, deltas in port_bytes.items():
                        total_bytes = sum(deltas)
                        gbps = total_bytes * 8 / duration / 1e9  # convert to Gbps
                        avg_throughputs.append(gbps)

                    cdf_arr = getCdfFromArray(avg_throughputs)
                    ax.plot([x[0] for x in cdf_arr],
                            [x[3] for x in cdf_arr],
                            markersize=0,
                            linewidth=3.0,
                            label=lb_mode)

        ax.legend(frameon=False, fontsize=12)
        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)
        mode_suffix = "IMB" if mode == "imbalance" else "THR"
        fname = f"CDF_{mode_suffix}_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}"
        fig.savefig(f"{fig_dir}/{fname}.pdf", bbox_inches='tight')
        plt.close()


if __name__ == "__main__":
    setup()
    main()
