#!/usr/bin/python3
"""
Parse FCT results into JSON files, grouped for comparison across different
switch BUFFER_SIZE values.

History-file lines are expected to carry the buffer-size as the last CSV
field (appended by mix/fix_history_buffer.py), e.g.:
    MM/DD/YY,<id>,...,0,3000,3000,0.44

Grouping key:
    (topo, netload, flow_control, load_type, error_rate,
     cc_mode, lb_mode, recovery, window, rto_high, rto_low)
so each output JSON contains one curve per buffer_size for a fixed
configuration -- ready to plot "FCT slowdown vs percentile" with
buffer_size as the varying legend.
"""

import subprocess
import os
import sys
import argparse
import json
from collections import defaultdict

# --- Dictionaries for mode mapping ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 5: "dcqcn_lane", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -----------------------------------------

topo2bdp = {
    "leaf_spine_L2_S8_100G_OS1": 104000,
    "bigswitch_H16_100G_OS1": 104000,
    "leaf_spine_128_100G_OS2": 104000, "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000, "leaf_spine_L16_S16_100G_OS1": 104000,
    "leaf_spine_L8_S8_400G_OS2": 404000,
    "leaf_spine_L8_S16_400G_OS1": 404000,
    "leaf_spine_L8_S16_200G_OS1": 204000,
    "fat_k8_400G_OS1": 606000,
    "fat_k8_100G_OS2": 153000, "fat_k8_100G_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_nofail_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_faill1_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_faill2_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_faill12_OS1": 153000,
    "three_layer_p4_tor4_l19_l24_s8_faill23_OS1": 153000,
    "three_layer_p4_tor4_l19_l28_s8_failhalf_OS1": 153000,
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1": 104000,
}


def getFilePath():
    return os.path.dirname(os.path.realpath(__file__))


def get_pctl(a, p):
    i = int(len(a) * p)
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0
    return a[i]


def get_steps_from_raw(filename, time_start, time_end, num_buckets=20):
    """Processes a raw FCT data file to extract slowdown statistics."""
    cmd_get_raw = (
        f"cat {filename} | awk '{{ if ($6 > {time_start} && $6+$7 < {time_end}) "
        f"{{ slow=$7/$8; print (slow<1?1:slow), $5}} }}'"
    )
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip():
            return {"avg": [], "p99": [], "size": []}
        raw_flows = [line.split() for line in output_raw.strip().split('\n')]
        raw_flows = [[float(f[0]), int(f[1])] for f in raw_flows if len(f) == 2]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"Warning: Command or parsing failed for {filename}. Returning empty result.")
        return {"avg": [], "p99": [], "size": []}

    flows_by_size = defaultdict(list)
    for slowdown, size in raw_flows:
        flows_by_size[size].append(slowdown)

    reordered_flows = []
    internal_reorder_buckets = 100
    for size in sorted(flows_by_size.keys()):
        slowdowns_for_size = sorted(flows_by_size[size])
        n_flows = len(slowdowns_for_size)
        if n_flows == 0:
            continue
        buckets = [[] for _ in range(internal_reorder_buckets)]
        for i, slowdown in enumerate(slowdowns_for_size):
            buckets[i % internal_reorder_buckets].append(slowdown)
        for bucket in buckets:
            for slowdown in bucket:
                reordered_flows.append([slowdown, size])

    if not reordered_flows:
        return {"avg": [], "p99": [], "size": []}

    aa = [f"{slowdown} {size}" for slowdown, size in reordered_flows]
    nn = len(aa)

    res = []
    for i in range(num_buckets):
        percentile_start = i * (100 / num_buckets)
        percentile_end = (i + 1) * (100 / num_buckets)

        l = int(percentile_start * nn / 100)
        r = int(percentile_end * nn / 100)
        if i == num_buckets - 1:
            r = nn

        current_res = [percentile_end / 100.]
        fct_size_chunk = aa[l:r]
        if not fct_size_chunk:
            current_res.extend([0, 0, 0, 0, 0, 0, 0, 0, 0])
            res.append(current_res)
            continue

        fct_size_chunk = [[float(x.split(" ")[0]), int(x.split(" ")[1])] for x in fct_size_chunk]
        fct = sorted(map(lambda x: x[0], fct_size_chunk))

        current_res.append(fct_size_chunk[-1][1])
        current_res.append(sum(fct) / len(fct))
        current_res.append(get_pctl(fct, 0.5))
        current_res.append(get_pctl(fct, 0.8))
        current_res.append(get_pctl(fct, 0.9))
        current_res.append(get_pctl(fct, 0.95))
        current_res.append(get_pctl(fct, 0.99))
        current_res.append(get_pctl(fct, 0.999))
        current_res.append(fct[-1])
        res.append(current_res)

    result = {"avg": [], "p50": [], "p80": [], "p90": [], "p95": [],
              "p99": [], "p999": [], "tail": [], "size": []}
    for item in res:
        if len(item) > 9:
            result["avg"].append(item[2])
            result["p50"].append(item[3])
            result["p80"].append(item[4])
            result["p90"].append(item[5])
            result["p95"].append(item[6])
            result["p99"].append(item[7])
            result["p999"].append(item[8])
            result["tail"].append(item[9])
            result["size"].append(item[1])
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Parse FCT results into JSON files grouped for buffer-size comparison.'
    )
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0)
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000)
    parser.add_argument('--allow-single', action='store_true',
                        help='Emit JSON even if a group has only one buffer_size.')
    args = parser.parse_args()

    time_start = args.time_limit_begin
    time_end = args.time_limit_end

    NUM_BUCKETS = 19

    file_dir = getFilePath()
    json_dir = os.path.join(file_dir, "json-data-fct-bufsz/")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    map_key_to_id = defaultdict(list)

    with open(history_filename, "r") as f:
        for line in f.readlines():
            for topo_prefix in topo2bdp.keys():
                if topo_prefix in line:
                    parsed = line.strip().split(',')
                    # Need the full 25-field row (with trailing buffer_size).
                    if len(parsed) < 25:
                        print(f"Skipping (no buffer_size field): {line.strip()}")
                        continue

                    cc_mode_id = int(parsed[2])
                    lb_mode_id = int(parsed[3])
                    irn = int(parsed[11])

                    if (cc_mode_id not in cc_modes or
                        lb_mode_id not in lb_modes or
                        irn not in irn_modes):
                        continue

                    config_id    = parsed[1]
                    ar_mode      = parsed[4]
                    pfc          = int(parsed[10])
                    window_size  = parsed[14]
                    topo         = parsed[15]
                    load_type    = parsed[17]
                    netload      = parsed[18]
                    error_rate   = parsed[19]
                    timeout_mode = parsed[21]
                    rto_high     = parsed[22]
                    rto_low      = parsed[23]
                    buffer_size  = parsed[24]

                    recovery_label = irn_modes.get(irn)
                    if ar_mode == '1':
                        if irn in (0, 1):
                            recovery_label = "RTO+GBN"
                        elif irn == 2:
                            recovery_label = "IdealTrimming"

                    if timeout_mode == '1':
                        if recovery_label == "RTO+GBN":
                            recovery_label = "RTO+GBN+slowstart"
                        elif recovery_label == "IdealTrimming":
                            recovery_label = "IdealTrimming+slowstart"
                        elif recovery_label == "Ideal":
                            recovery_label = "Ideal+slowstart"
                    elif timeout_mode == '2':
                        if recovery_label == "RTO+GBN":
                            recovery_label = "RTO+GBN+Now"

                    lb_mode_str = lb_modes.get(lb_mode_id)
                    cc_mode_str = cc_modes.get(cc_mode_id)
                    flow_control = "Lossless" if pfc == 1 else "Lossy"

                    # Group by everything *except* buffer_size so each
                    # output file compares buffer-size variants head-to-head.
                    key = (topo, netload, flow_control, load_type, error_rate,
                           cc_mode_str, lb_mode_str, recovery_label,
                           window_size, rto_high, rto_low)

                    entry_details = {
                        "config_id":   config_id,
                        "lb_mode":     lb_mode_str,
                        "cc_mode":     cc_mode_str,
                        "recovery":    recovery_label,
                        "timeout":     timeout_mode,
                        "window":      window_size,
                        "rto_high":    rto_high,
                        "rto_low":     rto_low,
                        "buffer_size": buffer_size,
                    }
                    map_key_to_id[key].append(entry_details)
                    break

    for k, v in map_key_to_id.items():
        x_axis_step = 100 / NUM_BUCKETS
        (topo, netload, flow_control, load_type, error_rate,
         cc_mode_str, lb_mode_str, recovery_label,
         window_size, rto_high, rto_low) = k

        plot_group_data = {
            "metadata": {
                "topology":         topo,
                "network_load":     netload,
                "flow_control":     flow_control,
                "load_type":        load_type,
                "error_rate":       error_rate,
                "congestion_control_mode": cc_mode_str,
                "load_balancing_mode":     lb_mode_str,
                "recovery_mechanism":      recovery_label,
                "window_size":      window_size,
                "rto_high":         rto_high,
                "rto_low":          rto_low,
            },
            "x_axis_percentiles": [(i + 1) * x_axis_step for i in range(NUM_BUCKETS)],
            "data_series": []
        }

        # Sort series by numeric buffer_size so the legend comes out ordered.
        def _bf_key(entry):
            try:
                return float(entry["buffer_size"])
            except ValueError:
                return float("inf")
        v_sorted = sorted(v, key=_bf_key)

        for entry in v_sorted:
            config_id = entry["config_id"]
            fct_slowdown_file = f"{output_dir}/{config_id}/{config_id}_out_fct.txt"
            if os.path.exists(fct_slowdown_file):
                result = get_steps_from_raw(fct_slowdown_file, time_start, time_end,
                                            num_buckets=NUM_BUCKETS)
                if result and result["avg"]:
                    series_data = {
                        "buffer_size":              entry["buffer_size"],
                        "config_id":                entry["config_id"],
                        "congestion_control_mode":  entry.get("cc_mode"),
                        "load_balancing_mode":      entry["lb_mode"],
                        "recovery_mechanism":       entry["recovery"],
                        "timeout_mode":             entry["timeout"],
                        "window_size":              entry["window"],
                        "rto_high":                 entry["rto_high"],
                        "rto_low":                  entry["rto_low"],
                        "avg_fct_slowdown":         result["avg"],
                        "p99_fct_slowdown":         result["p99"],
                        "flow_size_buckets_bytes":  result["size"],
                    }
                    plot_group_data["data_series"].append(series_data)

        if not plot_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid data.")
            continue

        # Need at least two buffer-size points for a meaningful comparison,
        # unless --allow-single is set.
        unique_bufsz = {s["buffer_size"] for s in plot_group_data["data_series"]}
        if len(unique_bufsz) < 2 and not args.allow_single:
            print(f"Skipping group {k}: only one buffer_size value ({unique_bufsz}).")
            continue

        json_filename = (
            f"{json_dir}/DATA_TOPO_{topo}_LOAD_{netload}_FC_{flow_control}"
            f"_TYPE_{load_type}_ERR_{error_rate}"
            f"_CC_{cc_mode_str}_LB_{lb_mode_str}_REC_{recovery_label}"
            f"_W_{window_size}_RTO_{rto_high}_{rto_low}.json"
        )
        # Sanitize path -- some recovery labels contain '+'.
        json_filename = json_filename.replace("+", "-plus-")

        print(f"Saving data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(plot_group_data, f, indent=4)


if __name__ == "__main__":
    main()
