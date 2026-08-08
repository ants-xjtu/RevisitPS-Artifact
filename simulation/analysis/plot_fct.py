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

# LB/CC mode matching
cc_modes = {
    1: "dcqcn",
    2: "dcqcn_dst",
    4: "none",
    3: "hp",
    7: "timely",
    8: "dctcp",
}
lb_modes = {
    0: "fecmp",
    1: "rps",
    2: "drill",
    3: "conga",
    4: "adaptive",  # Adaptive Routing Packet Spraying
    6: "letflow",
    9: "conweave",
}
topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,
    "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000,
    "leaf_spine_L16_S16_100G_OS1": 104000,
    "fat_k8_100G_OS2": 153000,
    "fat_k8_100G_OS1": 153000,
}

C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple',
    'xkcd:orange', 'xkcd:teal', 'xkcd:brick red',
    'xkcd:black', 'xkcd:brown', 'xkcd:grey',
]

LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D']
H = ['//', 'o', '***', 'x', 'xxx']

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

def get_pctl(a, p):
    i = int(len(a) * p)
    # Ensure index is within bounds
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0 # Or some other default for an empty list
    return a[i]

def size2str(steps):
    result = []
    for step in steps:
        if step < 10000:
            result.append("{:.1f}K".format(step / 1000))
        elif step < 1000000:
            result.append("{:.0f}K".format(step / 1000))
        else:
            result.append("{:.1f}M".format(step / 1000000))
    return result

def get_steps_from_raw(filename, time_start, time_end, step=5):
    cmd_slowdown = "cat %s"%(filename)+" | awk '{ if ($6>"+"%d"%time_start+" && $6+$7<"+"%d"%(time_end)+") { slow=$7/$8; print slow<1?1:slow, $5} }' | sort -n -k 2"
    try:
        output_slowdown = subprocess.check_output(cmd_slowdown, shell=True)
        aa = output_slowdown.decode("utf-8").split('\n')[:-2]
    except subprocess.CalledProcessError:
        print(f"Warning: Command failed for {filename}. Returning empty result.")
        return {"avg": [], "p99": [], "size": []}
    
    nn = len(aa)
    if nn == 0:
        return {"avg": [], "p99": [], "size": []}

    res = [[i/100.] for i in range(0, 100, step)]
    for i in range(0, 100, step):
        l = int(i * nn / 100)
        r = int((i+step) * nn / 100)
        fct_size = aa[l:r]
        if not fct_size:
            # If a bin is empty, we can't calculate stats. Append placeholders.
            res[int(i/step)].extend([0, 0, 0, 0, 0, 0])
            continue
            
        fct_size = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size]
        fct = sorted(map(lambda x: x[0], fct_size))
        
        res[int(i/step)].append(fct_size[-1][1])  # size
        res[int(i/step)].append(sum(fct) / len(fct))  # avg
        res[int(i/step)].append(get_pctl(fct, 0.5))
        res[int(i/step)].append(get_pctl(fct, 0.95))
        res[int(i/step)].append(get_pctl(fct, 0.99))
        res[int(i/step)].append(get_pctl(fct, 0.999))

    result = {"avg": [], "p99": [], "size": []}
    for item in res:
        if len(item) > 5: # Check if item was populated
            result["avg"].append(item[2])
            result["p99"].append(item[5])
            result["size"].append(item[1])

    return result

def main():
    parser = argparse.ArgumentParser(description='Plotting FCT of results')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end
    STEP = 5

    file_dir = getFilePath()
    fig_dir = file_dir + "/figures"
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = file_dir + "/../mix/output"
    history_filename = file_dir + "/../mix/history_21ls/history_21ls_50_Ali_0_slow0_lossy.txt"
    map_key_to_id = {}

    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo in topo2bdp.keys():
                if topo in line:
                    parsed = line.strip().split(',')
                    # 确保 history 文件至少有22列，以防万一
                    if len(parsed) < 22:
                        continue
                    
                    config_id = parsed[1]
                    cc_mode = cc_modes[int(parsed[2])]
                    lb_mode = lb_modes[int(parsed[3])]
                    fc = (int(parsed[10]), int(parsed[11]))
                    flow_control = "IRN" if fc == (0, 1) else "Lossless" if fc == (1, 0) else None
                    if not flow_control:
                        continue
                    
                    # vvvvvvvvv 这是修改的核心部分 vvvvvvvvv
                    window_size = parsed[14] # 根据新 history 格式，索引14是 window_size
                    topo = parsed[15]
                    load_type = parsed[17]
                    netload = parsed[18]
                    error_rate = parsed[19]
                    timeout_mode = parsed[21] # 根据新 history 格式，索引21是 timeout_slowstart_mode
                    
                    # 将新参数加入key中，用于分组
                    key = (topo, netload, flow_control, load_type, error_rate, window_size, timeout_mode)
                    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                    
                    map_key_to_id.setdefault(key, []).append([config_id, lb_mode])

    for k, v in map_key_to_id.items():
        # 预先生成x轴标签，避免只使用最后一次循环的结果
        x_tick_labels = []
        if v:
            representative_config_id, _ = v[0]
            fct_slowdown_rep = f"{output_dir}/{representative_config_id}/{representative_config_id}_out_fct.txt"
            if os.path.exists(fct_slowdown_rep):
                representative_result = get_steps_from_raw(fct_slowdown_rep, time_start, time_end, STEP)
                x_tick_labels = (['0'] + size2str(representative_result["size"]))[::2]

        xvals = [i for i in range(STEP, 100 + STEP, STEP)]

        ################## AVG plotting ##################
        fig, ax = plt.subplots(figsize=(4, 4), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("Avg FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')
        
        lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill", "rps", "adaptive"]
        for tgt_lbmode in lbmode_order:
            for vv in v:
                config_id, lb_mode = vv
                if lb_mode == tgt_lbmode:
                    fct_slowdown = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
                    if os.path.exists(fct_slowdown):
                        result = get_steps_from_raw(fct_slowdown, time_start, time_end, STEP)
                        ax.plot(xvals, result["avg"], markersize=1.0, linewidth=3.0, label=lb_mode)

        ax.legend(bbox_to_anchor=(0.0, 1.2), loc="upper left", frameon=False, fontsize=12, ncol=2)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        if x_tick_labels:
            ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        
        ax.autoscale(enable=False, axis='y')
        # ax.set_ylim(1, 8)
        
        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)

        # vvvvvvvvv 这是修改的核心部分 vvvvvvvvv
        fig_filename = f"{fig_dir}/AVG_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}_WIN_{k[5]}_TMT_{k[6]}.pdf"
        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()


        ################## P99 plotting ##################
        fig, ax = plt.subplots(figsize=(4, 4), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("p99 FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')
        
        for tgt_lbmode in lbmode_order:
            for vv in v:
                config_id, lb_mode = vv
                if lb_mode == tgt_lbmode:
                    fct_slowdown = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
                    if os.path.exists(fct_slowdown):
                        result = get_steps_from_raw(fct_slowdown, time_start, time_end, STEP)
                        ax.plot(xvals, result["p99"], markersize=1.0, linewidth=3.0, label=lb_mode)

        ax.legend(bbox_to_anchor=(0.0, 1.2), loc="upper left", frameon=False, fontsize=12, ncol=2)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        if x_tick_labels:
            ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        
        ax.autoscale(enable=False, axis='y')
        # ax.set_ylim(3, 30)

        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)

        # vvvvvvvvv 这是修改的核心部分 vvvvvvvvv
        fig_filename = f"{fig_dir}/P99_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}_WIN_{k[5]}_TMT_{k[6]}.pdf"
        # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

if __name__ == "__main__":
    setup()
    main()