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

# Adjusted color cycle for comparing two lines
C = [
    'xkcd:blue', 'xkcd:brick red', 'xkcd:grass green', 
    'xkcd:purple', 'xkcd:orange', 'xkcd:teal',
    'xkcd:black', 'xkcd:brown', 'xkcd:grey',
]

LS = ['solid', 'dashed', 'dotted', 'dashdot', (0, (3, 1, 1, 1))] # Added a new linestyle
M = ['o', 's', 'x', 'v', 'D']
H = ['//', 'o', '***', 'x', 'xxx']

def setup():
    # This setup function remains the same as the original.
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
    # Correctly gets the script's directory, assuming it's in the 'scripts' folder
    dir_path = os.path.dirname(os.path.realpath(__file__))
    print(f"File directory: {dir_path}")
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
            result.append(f"{step / 1000:.1f}K")
        elif step < 1000000:
            result.append(f"{step / 1000:.0f}K")
        else:
            result.append(f"{step / 1000000:.1f}M")
    return result

def get_steps_from_raw(filename, time_start, time_end, step=5):
    cmd_slowdown = f"cat {filename} | awk '{{ if ($6>{time_start} && $6+$7<{time_end}) {{ slow=$7/$8; print slow<1?1:slow, $5}} }}' | sort -n -k 2"
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
        fct_size_slice = aa[l:r]
        if not fct_size_slice:
            res[int(i/step)].extend([0, 0, 0, 0, 0, 0])
            continue
            
        fct_size_data = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size_slice]
        fct_values = sorted([x[0] for x in fct_size_data])
        
        res[int(i/step)].append(fct_size_data[-1][1])
        res[int(i/step)].append(sum(fct_values) / len(fct_values))
        res[int(i/step)].append(get_pctl(fct_values, 0.5))
        res[int(i/step)].append(get_pctl(fct_values, 0.95))
        res[int(i/step)].append(get_pctl(fct_values, 0.99))
        res[int(i/step)].append(get_pctl(fct_values, 0.999))

    result = {"avg": [], "p99": [], "size": []}
    for item in res:
        if len(item) > 5:
            result["avg"].append(item[2])
            result["p99"].append(item[5])
            result["size"].append(item[1])

    return result

# vvvvvvvvv 【核心修改】在这里修改判断逻辑 vvvvvvvvv
def get_experiment_label(flow_control, window_size, timeout_mode):
    """Generates a descriptive label for the plot legend."""
    ws = int(window_size)
    tm = int(timeout_mode)
    
    if flow_control == "IRN":
        if tm == 0: return "IRN (tm=0)"
        if tm == 1: return "IRN (tm=1)"
    elif flow_control == "Lossless":
        if ws == 0: return "Lossless (win=0)"
        if ws == 104000: return "Lossless (win=104KB)"
        if ws == 512000: return "Lossless (win=512KB)"
    return None # Return None for configs we don't want to plot
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

def main():
    parser = argparse.ArgumentParser(description='Plotting FCT of results')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end
    STEP = 5

    file_dir = getFilePath()
    
    history_dir = os.path.abspath(os.path.join(file_dir, "..", "mix", "history_21ls"))
    history_files_to_parse = [
        os.path.join(history_dir, "history_21ls_80_Ali_0_slow0_lossy.txt"),
        os.path.join(history_dir, "history_21ls_80_Ali_0_slow1_lossy.txt"),
        os.path.join(history_dir, "history_21ls_80_Ali_0_slow0_lossless_w0.txt"),
        os.path.join(history_dir, "history_21ls_80_Ali_0_slow0_lossless_w104.txt"),
        os.path.join(history_dir, "history_21ls_80_Ali_0_slow0_lossless_w512.txt"),
    ]

    fig_dir = os.path.join(file_dir, "fct_vs_figures_5_way")
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir)
    output_dir = os.path.abspath(os.path.join(file_dir, "..", "mix", "output"))

    grouped_configs = {}

    for history_file in history_files_to_parse:
        if not os.path.exists(history_file):
            print(f"Warning: History file not found at {history_file}. Skipping.")
            continue
        
        print(f"Reading history from: {history_file}")
        with open(history_file, "r") as f:
            for line in f.readlines():
                for topo_prefix in topo2bdp.keys():
                    if topo_prefix in line:
                        parsed = line.strip().split(',')
                        if len(parsed) < 22: continue

                        config_id = parsed[1]
                        lb_mode = lb_modes[int(parsed[3])]
                        fc_tuple = (int(parsed[10]), int(parsed[11]))
                        flow_control = "IRN" if fc_tuple == (0, 1) else "Lossless" if fc_tuple == (1, 0) else None
                        
                        window_size = parsed[14]
                        topo = parsed[15]
                        load_type = parsed[17]
                        netload = parsed[18]
                        error_rate = parsed[19]
                        timeout_mode = parsed[21]
                        
                        label = get_experiment_label(flow_control, window_size, timeout_mode)
                        
                        # (您可以保留或删除这里的调试信息)
                        # print(f"DEBUG: FC='{flow_control}', Win='{window_size}', TMT='{timeout_mode}' -> Label='{label}'")
                        
                        if label is None:
                            continue

                        group_key = (topo, netload, load_type, error_rate)

                        if group_key not in grouped_configs:
                            grouped_configs[group_key] = {}
                        if lb_mode not in grouped_configs[group_key]:
                            grouped_configs[group_key][lb_mode] = {}
                        
                        grouped_configs[group_key][lb_mode][label] = config_id
                        break

    lbmode_order = ["fecmp", "conga", "letflow", "conweave", "drill", "rps", "adaptive"]
    
    # Main plotting loop
    for group_key, lb_data in grouped_configs.items():
        topo, netload, load_type, error_rate = group_key
        
        x_tick_labels = []
        rep_cid = None
        for lb_mode in lbmode_order:
            if lb_mode in lb_data:
                rep_cid = next(iter(lb_data[lb_mode].values()), None)
                if rep_cid: break
        
        if rep_cid:
            fct_rep_file = f"{output_dir}/{rep_cid}/{rep_cid}_out_fct.txt"
            if os.path.exists(fct_rep_file):
                rep_result = get_steps_from_raw(fct_rep_file, time_start, time_end, STEP)
                x_tick_labels = (['0'] + size2str(rep_result["size"]))[::2]
        
        xvals = [i for i in range(STEP, 100 + STEP, STEP)]

        for tgt_lbmode in lbmode_order:
            if tgt_lbmode not in lb_data:
                continue

            config_to_plot = lb_data[tgt_lbmode]

            # ################## AVG plotting ##################
            fig, ax = plt.subplots(figsize=(4, 4), constrained_layout=True)
            ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
            ax.set_ylabel("Avg FCT Slowdown", fontsize=11.5)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
            for label, config_id in sorted(config_to_plot.items()):
                fct_file = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
                if os.path.exists(fct_file):
                    result = get_steps_from_raw(fct_file, time_start, time_end, STEP)
                    if result["avg"]:
                        ax.plot(xvals, result["avg"], markersize=2.0, linewidth=3.0, label=label)
            
            ax.legend(loc="upper left", frameon=False, fontsize=10)
            ax.tick_params(axis="x", rotation=40)
            ax.set_xticks(([0] + xvals)[::2])
            if x_tick_labels:
                ax.set_xticklabels(x_tick_labels, fontsize=10.5)
            ax.set_yscale("log")
            ax.grid(which='major', alpha=0.5, linestyle='-')
            ax.grid(which='minor', alpha=0.2, linestyle=':')
            
            fig_filename = f"{fig_dir}/AVG_LB_{tgt_lbmode}_TOPO_{topo}_LOAD_{netload}_TYPE_{load_type}_ERR_{error_rate}.pdf"
            print(f"Saving figure: {fig_filename}")
            plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
            plt.close()

            # ################## P99 plotting ##################
            fig, ax = plt.subplots(figsize=(4, 4), constrained_layout=True)
            ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
            ax.set_ylabel("p99 FCT Slowdown", fontsize=11.5)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
            for label, config_id in sorted(config_to_plot.items()):
                fct_file = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
                if os.path.exists(fct_file):
                    result = get_steps_from_raw(fct_file, time_start, time_end, STEP)
                    if result["p99"]:
                        ax.plot(xvals, result["p99"], markersize=2.0, linewidth=3.0, label=label)

            ax.legend(loc="upper left", frameon=False, fontsize=10)
            ax.tick_params(axis="x", rotation=40)
            ax.set_xticks(([0] + xvals)[::2])
            if x_tick_labels:
                ax.set_xticklabels(x_tick_labels, fontsize=10.5)
            ax.set_yscale("log")
            ax.grid(which='major', alpha=0.5, linestyle='-')
            ax.grid(which='minor', alpha=0.2, linestyle=':')

            fig_filename = f"{fig_dir}/P99_LB_{tgt_lbmode}_TOPO_{topo}_LOAD_{netload}_TYPE_{load_type}_ERR_{error_rate}.pdf"
            print(f"Saving figure: {fig_filename}")
            plt.savefig(fig_filename, transparent=False, bbox_inches='tight')
            plt.close()

if __name__ == "__main__":
    setup()
    main()