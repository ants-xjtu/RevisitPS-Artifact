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
    3: "hp",
    7: "timely",
    8: "dctcp",
}
lb_modes = {
    0: "fecmp",
    2: "drill",
    3: "conga",
    6: "letflow",
    9: "conweave",
}
topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,
    "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000,
    "fat_k4_100G_OS2": 153000,
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

def get_steps_from_raw(filename, time_start, time_end, src_node=None, dst_node=None, step=5):
    # Script data format assumptions:
    # $1 = Source ID
    # $2 = Destination ID
    # $5 = Flow Size
    # $6 = Start Time
    # $7 = Flow Completion Time (FCT)
    # $8 = Ideal FCT

    # Base filter for time
    time_filter = f"$6>{time_start} && $6+$7<{time_end}"
    
    filter_condition = time_filter
    
    # Add source node filter if specified
    if src_node is not None:
        filter_condition += f" && $1=={src_node}"

    # Add destination node filter if specified
    if dst_node is not None:
        filter_condition += f" && $2=={dst_node}"

    cmd_slowdown = f"cat {filename} | awk '{{ if ({filter_condition}) {{ slow=$7/$8; print slow<1?1:slow, $5}} }}' | sort -n -k 2"

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
              res[int(i/step)].extend([0, 0, 0, 0, 0, 0])
              continue
            
        fct_size = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size]
        fct = sorted(map(lambda x: x[0], fct_size))
        
        res[int(i/step)].append(fct_size[-1][1])
        res[int(i/step)].append(sum(fct) / len(fct))
        res[int(i/step)].append(get_pctl(fct, 0.5))
        res[int(i/step)].append(get_pctl(fct, 0.95))
        res[int(i/step)].append(get_pctl(fct, 0.99))
        res[int(i/step)].append(get_pctl(fct, 0.999))

    result = {"avg": [], "p99": [], "size": []}
    for item in res:
        if len(item) > 5:
            result["avg"].append(item[2])
            result["p99"].append(item[5])
            result["size"].append(item[1])

    return result

def main():
    parser = argparse.ArgumentParser(description='Plotting FCT of results')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    parser.add_argument('--src', dest='src_node', type=int, default=None,
                        help='Filter flows by a specific source node ID.')
    parser.add_argument('--dst', dest='dst_node', type=int, default=None,
                        help='Filter flows by a specific destination node ID.')
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end
    src_node = args.src_node
    dst_node = args.dst_node
    STEP = 5

    file_dir = getFilePath()
    fig_dir = file_dir + "/figures"
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = file_dir + "/../mix/output"
    history_filename = file_dir + "/../mix/history_80_compare_drill_lossless_datacorruption.txt"

    map_key_no_err = {}

    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo in topo2bdp.keys():
                if topo in line:
                    parsed = line.strip().split(',')
                    config_id = parsed[1]
                    lb_mode = lb_modes[int(parsed[3])]
                    if lb_mode != "drill":
                        continue  # 只分析 drill
                    
                    fc = (int(parsed[10]), int(parsed[11]))
                    flow_control = "IRN" if fc == (0, 1) else "Lossless" if fc == (1, 0) else None
                    if not flow_control:
                        continue
                    topo = parsed[14]
                    load_type = parsed[16]
                    netload = parsed[17]
                    error_rate = parsed[18]
                    key = (topo, netload, flow_control, load_type)
                    map_key_no_err.setdefault(key, {})[error_rate] = config_id

    for key, err_dict in map_key_no_err.items():
        print(f"\n{'='*80}")
        print(f"🚀 Drill Performance vs Error Rate for Config: {key}")
        print(f"{'='*80}")

        all_results = {}
        for error_rate, config_id in err_dict.items():
            fct_slowdown_path = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
            if os.path.exists(fct_slowdown_path):
                result = get_steps_from_raw(fct_slowdown_path, time_start, time_end, src_node, dst_node, STEP)
                if result["avg"]:
                    all_results[error_rate] = result

        if not all_results:
            print("No valid drill results found for this configuration. Skipping.")
            continue

        # Get flow size buckets and x-ticks
        representative_result = next(iter(all_results.values()))
        flow_size_upper_bounds = representative_result["size"]
        x_tick_labels = (['0'] + size2str(flow_size_upper_bounds))[::2]
        xvals = [i for i in range(STEP, 100 + STEP, STEP)]

        #################### 输出性能表格 ####################
        print("\n--- 📊 Drill Slowdown Breakdown by Error Rate ---")
        for error_rate, result in sorted(all_results.items()):
            print(f"\n[Error Rate: {error_rate}]")
            print(f"{'Flow Size Bucket':<20} {'Avg Slowdown':<20} {'P99 Slowdown':<20}")
            print(f"{'-'*19:<20} {'-'*19:<20} {'-'*19:<20}")
            for i in range(len(result['avg'])):
                size_label = f"<= {size2str([flow_size_upper_bounds[i]])[0]}"
                avg_val = f"{result['avg'][i]:.2f}"
                p99_val = f"{result['p99'][i]:.2f}"
                print(f"{size_label:<20} {avg_val:<20} {p99_val:<20}")

        #################### 输出对比表格 ####################
        print("\n--- 📈 Drill Speedup Comparison Between Error Rates ---")
        base_key = sorted(all_results.keys())[0]
        base = all_results[base_key]

        for compare_key in sorted(all_results.keys())[1:]:
            compare = all_results[compare_key]
            print(f"\nComparing Error Rate: {compare_key} vs Base: {base_key}")
            print(f"{'Flow Size Bucket':<20} {'Avg Speedup':<25} {'P99 Speedup':<25}")
            print(f"{'-'*19:<20} {'-'*24:<25} {'-'*24:<25}")
            for i in range(len(base['avg'])):
                size_label = f"<= {size2str([flow_size_upper_bounds[i]])[0]}"
                if base['avg'][i] > 0 and compare['avg'][i] > 0:
                    avg_ratio = base['avg'][i] / compare['avg'][i]
                    p99_ratio = base['p99'][i] / compare['p99'][i]
                    print(f"{size_label:<20} {avg_ratio:.2f}x faster       {p99_ratio:.2f}x faster")

        #################### 绘图 - avg ####################
        fig, ax = plt.subplots(figsize=(5, 4), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("Avg FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')

        for error_rate, result in sorted(all_results.items()):
            ax.plot(xvals, result["avg"], linewidth=2.0, label=f"err={error_rate}")

        ax.legend(frameon=False, fontsize=10)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)

        fig_filename = f"{fig_dir}/DRILL_AVG_COMPARE_ERR_TOPO_{key[0]}_LOAD_{key[1]}_FC_{key[2]}_TYPE_{key[3]}.pdf"
        print(f"\nSaving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

        #################### 绘图 - p99 ####################
        fig, ax = plt.subplots(figsize=(5, 4), constrained_layout=True)
        ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
        ax.set_ylabel("p99 FCT Slowdown", fontsize=11.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.yaxis.set_ticks_position('left')
        ax.xaxis.set_ticks_position('bottom')

        for error_rate, result in sorted(all_results.items()):
            ax.plot(xvals, result["p99"], linewidth=2.0, label=f"err={error_rate}")

        ax.legend(frameon=False, fontsize=10)
        ax.tick_params(axis="x", rotation=40)
        ax.set_xticks(([0] + xvals)[::2])
        ax.set_xticklabels(x_tick_labels, fontsize=10.5)
        ax.set_yscale("log")
        ax.grid(which='minor', alpha=0.2)
        ax.grid(which='major', alpha=0.5)

        fig_filename = f"{fig_dir}/DRILL_P99_COMPARE_ERR_TOPO_{key[0]}_LOAD_{key[1]}_FC_{key[2]}_TYPE_{key[3]}.pdf"
        print(f"Saving figure: {fig_filename}")
        plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
        plt.close()

if __name__ == "__main__":
    setup()
    main()