#!/usr/bin/python3
# 檔名: plot_error_comparison.py
# 功能: 在相同配置下，智能選擇一致的恢復機制，對比不同Error Rate對FCT Slowdown曲線的影響

import subprocess
import os
import argparse
import matplotlib as mpl
import matplotlib.pyplot as plt
from collections import defaultdict, Counter
import math
from cycler import cycler

# --- 輔助函數 ---
lb_modes_map = {
    "fecmp": 0, "rps": 1, "drill": 2, "conga": 3, "adaptive": 4, "letflow": 6, "conweave": 9,
}
# NEW: 增加irn_modes用於識別恢復機制
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN", 2: "DCP",
}

C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange',
    'xkcd:teal', 'xkcd:brick red', 'xkcd:black', 'xkcd:brown', 'xkcd:grey',
]
LS = ['solid', 'dashed', 'dotted', 'dashdot']
M = ['o', 's', 'x', 'v', 'D', '^', '<', '>']

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
    # ... (此函數保持不變) ...
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
    parser = argparse.ArgumentParser(description='Plot FCT slowdown comparison across different error rates.')
    parser.add_argument('history_files', nargs='+', type=str, help='Paths to the classified history files to plot.')
    parser.add_argument('--lb_mode', type=str, required=True, choices=lb_modes_map.keys(), help='The load balancing mode to analyze.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    args = parser.parse_args()

    setup()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "..", "mix", "output")
    fig_dir = os.path.join(script_dir, "figures_error_rate")
    os.makedirs(fig_dir, exist_ok=True)

    target_lb_id = lb_modes_map[args.lb_mode]
    
    # --- STAGE 1: DATA COLLECTION ---
    # NEW: 使用嵌套字典儲存數據: {error_rate: {recovery_label: fct_data}}
    data_collection = defaultdict(dict)
    common_params_str = ""
    
    for history_file in args.history_files:
        with open(history_file, 'r') as f:
            for line in f.readlines():
                if ',' not in line: continue
                parsed = line.strip().split(',')
                if len(parsed) < 22: continue

                try:
                    config_id = parsed[1]
                    lb_mode_id = int(parsed[3])
                    ar_mode = parsed[4]
                    irn = int(parsed[11])
                    error_rate = float(parsed[19])

                    if lb_mode_id == target_lb_id:
                        # 確定恢復機制標籤
                        recovery_label = "Unknown"
                        if ar_mode != '0':
                            recovery_label = "AR-Go-Back-N"
                        else:
                            recovery_label = irn_modes.get(irn, "Unknown")

                        fct_file = os.path.join(output_dir, config_id, f"{config_id}_out_fct.txt")
                        if os.path.exists(fct_file):
                            fct_results = get_steps_from_raw(fct_file, args.time_limit_begin, args.time_limit_end)
                            if fct_results and fct_results["avg"]:
                                data_collection[error_rate][recovery_label] = fct_results
                                
                                if not common_params_str:
                                    basename, _ = os.path.splitext(os.path.basename(history_file))
                                    parts = basename.split('_')
                                    common_params_str = f"TOPO_{parts[1]}_LOAD_{parts[2]}_CDF_{parts[3]}_TMT_{parts[5]}_FC_{parts[6]}_WIN_{parts[7]}_LB_{args.lb_mode}"

                except (ValueError, IndexError) as e:
                    print(f"Skipping malformed line: {line.strip()} | Error: {e}")
                    continue

    if not data_collection:
        print(f"No valid data found for LB mode '{args.lb_mode}' in the provided files.")
        return

    # --- STAGE 2: INTELLIGENT SELECTION ---
    # 找出非零錯誤率中的主流恢復機制
    recovery_mechanism_counter = Counter()
    for err_rate, recovery_data in data_collection.items():
        if err_rate > 0:
            for label in recovery_data.keys():
                recovery_mechanism_counter[label] += 1
    
    if not recovery_mechanism_counter:
        # 如果只有err=0的數據，就隨便選一個
        target_recovery_mechanism = next(iter(data_collection[0.0].keys()), None)
    else:
        target_recovery_mechanism = recovery_mechanism_counter.most_common(1)[0][0]

    if not target_recovery_mechanism:
        print("Could not determine a target recovery mechanism to plot.")
        return
        
    print(f"--> Smart Selection: Plotting with consistent recovery mechanism '{target_recovery_mechanism}'")

    # 根據主流機制，篩選出最終要繪圖的數據
    results_by_error_rate = {}
    for err_rate, recovery_data in data_collection.items():
        if target_recovery_mechanism in recovery_data:
            results_by_error_rate[err_rate] = recovery_data[target_recovery_mechanism]

    # --- STAGE 3: PLOTTING ---
    STEP = 5
    xvals = [i for i in range(STEP, 100 + STEP, STEP)]
    x_tick_labels = []
    if not results_by_error_rate:
        print(f"No data points found for the selected recovery mechanism '{target_recovery_mechanism}'.")
        return
        
    first_result = next(iter(results_by_error_rate.values()))
    if first_result["size"]:
        x_tick_labels = (['0'] + size2str(first_result["size"]))[::2]

    # --- AVG Plot ---
    fig, ax = plt.subplots(figsize=(4.5, 4.5), constrained_layout=True)
    for err_rate, results in sorted(results_by_error_rate.items()):
        label = f"ERR: {err_rate:.0e}" if err_rate != 0 else "ERR: 0.0"
        ax.plot(xvals, results['avg'], label=label, linewidth=3.0)

    ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
    ax.set_ylabel("Avg FCT Slowdown", fontsize=11.5)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(title=f"LB: {args.lb_mode.upper()} ({target_recovery_mechanism})", frameon=False, ncol=1) # 更新圖例標題
    ax.tick_params(axis="x", rotation=40)
    ax.set_xticks(([0] + xvals)[::2])
    if x_tick_labels: ax.set_xticklabels(x_tick_labels, fontsize=10.5)
    ax.set_yscale("log")
    ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
    
    fig_filename = os.path.join(fig_dir, f"AVG_ERROR_COMP_{common_params_str}_RECOVERY_{target_recovery_mechanism}.pdf") # 更新檔名
    print(f"Saving figure: {fig_filename}")
    plt.savefig(fig_filename, transparent=False, bbox_inches='tight'); plt.close()
    
    # --- P99 Plot ---
    fig, ax = plt.subplots(figsize=(4.5, 4.5), constrained_layout=True)
    ax.set_prop_cycle(None) 
    for err_rate, results in sorted(results_by_error_rate.items()):
        label = f"ERR: {err_rate:.0e}" if err_rate != 0 else "ERR: 0.0"
        ax.plot(xvals, results['p99'], label=label, linewidth=3.0)

    ax.set_xlabel("Flow Size (Bytes)", fontsize=11.5)
    ax.set_ylabel("p99 FCT Slowdown", fontsize=11.5)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(title=f"LB: {args.lb_mode.upper()} ({target_recovery_mechanism})", frameon=False, ncol=1) # 更新圖例標題
    ax.tick_params(axis="x", rotation=40)
    ax.set_xticks(([0] + xvals)[::2])
    if x_tick_labels: ax.set_xticklabels(x_tick_labels, fontsize=10.5)
    ax.set_yscale("log")
    ax.grid(which='minor', alpha=0.2); ax.grid(which='major', alpha=0.5)
    
    fig_filename = os.path.join(fig_dir, f"P99_ERROR_COMP_{common_params_str}_RECOVERY_{target_recovery_mechanism}.pdf") # 更新檔名
    print(f"Saving figure: {fig_filename}")
    plt.savefig(fig_filename, transparent=False, bbox_inches='tight'); plt.close()

if __name__ == "__main__":
    main()