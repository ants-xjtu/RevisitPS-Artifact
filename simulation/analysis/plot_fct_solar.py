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

# LB/CC mode matching
cc_modes = {
    1: "dcqcn",
    2: "dcqcn_dst",
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
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0
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
    # ✅ **函数重写 (第三版)**: 完全按照轮询分发和拼接桶的逻辑重写
    
    # 1. 获取原始 "slowdown size" 数据
    cmd_get_raw = f"cat {filename} | awk '{{ if ($6 > {time_start} && $6+$7 < {time_end}) {{ slow=$7/$8; print (slow<1?1:slow), $5}} }}'"
    
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip():
            return {"avg": [], "p99": [], "size": []}
        raw_flows = [line.split() for line in output_raw.strip().split('\n')]
        raw_flows = [[float(f[0]), int(f[1])] for f in raw_flows if len(f) == 2]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"Warning: Command or parsing failed for {filename}. Returning empty result.")
        return {"avg": [], "p99": [], "size": []}

    # 2. 按 flow size 进行分组
    flows_by_size = defaultdict(list)
    for slowdown, size in raw_flows:
        flows_by_size[size].append(slowdown)

    # 3. 对每个size分组进行重排序，并生成最终的、经过重排序的总列表
    reordered_flows = []
    num_buckets = 100
    
    # 按size大小顺序处理，以保证最终列表的基准顺序
    for size in sorted(flows_by_size.keys()):
        # a. 将当前size的所有slowdown从小到大排序
        slowdowns_for_size = sorted(flows_by_size[size])
        
        n_flows = len(slowdowns_for_size)
        if n_flows == 0:
            continue
            
        # b. 创建10个桶
        buckets = [[] for _ in range(num_buckets)]
        
        # c. 将排好序的流，通过轮询的方式(i % 10)放入各个桶
        for i, slowdown in enumerate(slowdowns_for_size):
            buckets[i % num_buckets].append(slowdown)
            
        # d. 按顺序拼接所有桶，形成新的数据序列
        for bucket in buckets:
            for slowdown in bucket:
                reordered_flows.append([slowdown, size])

    if not reordered_flows:
        return {"avg": [], "p99": [], "size": []}
        
    # 4. 将重排序后的数据列表，转换成后续代码期望的格式
    aa = [f"{slowdown} {size}" for slowdown, size in reordered_flows]
    
    # 5. 在这个新的数据序列上，执行原来的百分位绘图点计算逻辑
    nn = len(aa)
    res = [[i/100.] for i in range(0, 100, step)]
    for i in range(0, 100, step):
        l = int(i * nn / 100)
        r = int((i+step) * nn / 100)
        fct_size_chunk = aa[l:r]
        if not fct_size_chunk:
            res[int(i/step)].extend([0, 0, 0, 0, 0, 0])
            continue
            
        fct_size_chunk = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size_chunk]
        fct = sorted(map(lambda x: x[0], fct_size_chunk))
        
        res[int(i/step)].append(fct_size_chunk[-1][1])  # size
        res[int(i/step)].append(sum(fct) / len(fct))      # avg
        res[int(i/step)].append(get_pctl(fct, 0.5))       # p50
        res[int(i/step)].append(get_pctl(fct, 0.95))      # p95
        res[int(i/step)].append(get_pctl(fct, 0.99))      # p99
        res[int(i/step)].append(get_pctl(fct, 0.999))     # p999

    result = {"avg": [], "p99": [], "size": []}
    for item in res:
        if len(item) > 5:
            result["avg"].append(item[2])
            result["p99"].append(item[5])
            result["size"].append(item[1])

    return result

def main():
    # main 函数和绘图逻辑完全不变
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
    history_filename = file_dir + "/../mix/history_21ls_80_Solar_0_slow0_lossless.txt"
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
                    window_size = parsed[14]
                    topo = parsed[15]
                    load_type = parsed[17] # cdf
                    netload = parsed[18]
                    error_rate = parsed[19]
                    timeout_mode = parsed[21]
                    
                    # 将新参数加入key中，用于分组
                    key = (topo, netload, flow_control, load_type, error_rate, window_size, timeout_mode)
                    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                    
                    map_key_to_id.setdefault(key, []).append([config_id, lb_mode])

    for k, v in map_key_to_id.items():
        x_tick_labels = []
        if v:
            representative_config_id, _ = v[0]
            fct_slowdown_rep = f"{output_dir}/{representative_config_id}/{representative_config_id}_out_fct.txt"
            if os.path.exists(fct_slowdown_rep):
                representative_result = get_steps_from_raw(fct_slowdown_rep, time_start, time_end, STEP)
                if representative_result and representative_result["size"]:
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
        
        lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill", "rps"]
        for tgt_lbmode in lbmode_order:
            for vv in v:
                config_id, lb_mode = vv
                if lb_mode == tgt_lbmode:
                    fct_slowdown = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
                    if os.path.exists(fct_slowdown):
                        result = get_steps_from_raw(fct_slowdown, time_start, time_end, STEP)
                        if result and result["avg"]:
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
                        if result and result["p99"]:
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