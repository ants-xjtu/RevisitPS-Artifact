#!/usr/bin/python3
"""
Convert each split history file (one per <topo, buffer_size>) into its own
JSON of FCT-slowdown curves, one curve per run inside the split file.

Input:   mix/history_diffbw/split/<topo>__bufsz_<buf>.txt
Output:  parser/json-data-fct-split/<topo>__bufsz_<buf>.json

Each JSON's "data_series" has one entry per simulation in the split file,
labelled by (lb_mode, cc_mode, recovery, window, rto_high, rto_low), so a
single file is ready to plot "FCT slowdown vs percentile" for that
(topo, buffer_size) combination.
"""

import os
import sys
import glob
import json
import argparse
import subprocess
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 5: "dcqcn_lane", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SPLIT_DIR  = os.path.join(SCRIPT_DIR, "..", "mix", "history_diffbw", "100G-fattree")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "mix", "output")
JSON_DIR   = os.path.join(SCRIPT_DIR, "json-data-fct-split")


def get_pctl(a, p):
    i = int(len(a) * p)
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0
    return a[i]


def get_steps_from_raw(filename, time_start, time_end, num_buckets=19):
    cmd = (
        f"cat {filename} | awk '{{ if ($6 > {time_start} && $6+$7 < {time_end}) "
        f"{{ slow=$7/$8; print (slow<1?1:slow), $5}} }}'"
    )
    try:
        output_raw = subprocess.check_output(cmd, shell=True).decode("utf-8")
        if not output_raw.strip():
            return None
        raw_flows = [line.split() for line in output_raw.strip().split('\n')]
        raw_flows = [[float(f[0]), int(f[1])] for f in raw_flows if len(f) == 2]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"  Warning: awk/parse failed on {filename}")
        return None

    if not raw_flows:
        return None

    flows_by_size = defaultdict(list)
    for slowdown, size in raw_flows:
        flows_by_size[size].append(slowdown)

    reordered = []
    internal = 100
    for size in sorted(flows_by_size.keys()):
        slow_sorted = sorted(flows_by_size[size])
        buckets = [[] for _ in range(internal)]
        for i, s in enumerate(slow_sorted):
            buckets[i % internal].append(s)
        for b in buckets:
            for s in b:
                reordered.append([s, size])

    if not reordered:
        return None

    nn = len(reordered)
    result = {"avg": [], "p50": [], "p80": [], "p90": [], "p95": [],
              "p99": [], "p999": [], "tail": [], "size": []}

    for i in range(num_buckets):
        pct_s = i * (100 / num_buckets)
        pct_e = (i + 1) * (100 / num_buckets)
        l = int(pct_s * nn / 100)
        r = nn if i == num_buckets - 1 else int(pct_e * nn / 100)
        chunk = reordered[l:r]
        if not chunk:
            for k in ("avg", "p50", "p80", "p90", "p95", "p99", "p999", "tail", "size"):
                result[k].append(0)
            continue
        fct = sorted(x[0] for x in chunk)
        result["size"].append(chunk[-1][1])
        result["avg"].append(sum(fct) / len(fct))
        result["p50"].append(get_pctl(fct, 0.5))
        result["p80"].append(get_pctl(fct, 0.8))
        result["p90"].append(get_pctl(fct, 0.9))
        result["p95"].append(get_pctl(fct, 0.95))
        result["p99"].append(get_pctl(fct, 0.99))
        result["p999"].append(get_pctl(fct, 0.999))
        result["tail"].append(fct[-1])
    return result


def recovery_label(ar_mode: str, irn: int, timeout_mode: str) -> str:
    label = irn_modes.get(irn, "unknown")
    if ar_mode == '1':
        if irn in (0, 1):
            label = "RTO+GBN"
        elif irn == 2:
            label = "IdealTrimming"
    if timeout_mode == '1':
        if label == "RTO+GBN":
            label = "RTO+GBN+slowstart"
        elif label == "IdealTrimming":
            label = "IdealTrimming+slowstart"
        elif label == "Ideal":
            label = "Ideal+slowstart"
    elif timeout_mode == '2':
        if label == "RTO+GBN":
            label = "RTO+GBN+Now"
    return label


def process_split_file(split_path: str, time_start: int, time_end: int,
                       num_buckets: int = 19):
    entries = []
    topo_seen = set()
    bufsz_seen = set()

    with open(split_path) as f:
        for raw in f:
            line = raw.strip()
            if not line or not line[0:2].isdigit():
                continue
            fields = line.split(",")
            if len(fields) < 25:
                continue
            try:
                cc_id  = int(fields[2])
                lb_id  = int(fields[3])
                irn    = int(fields[11])
                pfc    = int(fields[10])
            except ValueError:
                continue
            if cc_id not in cc_modes or lb_id not in lb_modes or irn not in irn_modes:
                continue

            entry = {
                "config_id":   fields[1],
                "cc_mode":     cc_modes[cc_id],
                "lb_mode":     lb_modes[lb_id],
                "flow_control":"Lossless" if pfc == 1 else "Lossy",
                "recovery":    recovery_label(fields[4], irn, fields[21]),
                "timeout":     fields[21],
                "window":      fields[14],
                "topo":        fields[15],
                "load_type":   fields[17],
                "netload":     fields[18],
                "error_rate":  fields[19],
                "rto_high":    fields[22],
                "rto_low":     fields[23],
                "buffer_size": fields[24],
            }
            topo_seen.add(entry["topo"])
            bufsz_seen.add(entry["buffer_size"])
            entries.append(entry)

    if not entries:
        print(f"[skip] {os.path.basename(split_path)}: no parseable entries")
        return

    topo  = next(iter(topo_seen))  if len(topo_seen)  == 1 else "mixed"
    bufsz = next(iter(bufsz_seen)) if len(bufsz_seen) == 1 else "mixed"

    x_axis_step = 100 / num_buckets
    out = {
        "metadata": {
            "topology":    topo,
            "buffer_size": bufsz,
            "source":      os.path.relpath(split_path, start=os.path.dirname(SCRIPT_DIR)),
            "num_runs":    len(entries),
        },
        "x_axis_percentiles": [(i + 1) * x_axis_step for i in range(num_buckets)],
        "data_series": [],
    }

    for e in entries:
        fct_file = os.path.join(OUTPUT_DIR, e["config_id"],
                                f"{e['config_id']}_out_fct.txt")
        if not os.path.exists(fct_file):
            print(f"  [miss] fct file not found: {fct_file}")
            continue
        res = get_steps_from_raw(fct_file, time_start, time_end, num_buckets)
        if not res or not res["avg"]:
            print(f"  [empty] no FCT data for {e['config_id']}")
            continue
        out["data_series"].append({
            "config_id":               e["config_id"],
            "congestion_control_mode": e["cc_mode"],
            "load_balancing_mode":     e["lb_mode"],
            "flow_control":            e["flow_control"],
            "recovery_mechanism":      e["recovery"],
            "timeout_mode":            e["timeout"],
            "window_size":             e["window"],
            "load_type":               e["load_type"],
            "network_load":            e["netload"],
            "error_rate":              e["error_rate"],
            "rto_high":                e["rto_high"],
            "rto_low":                 e["rto_low"],
            "buffer_size":             e["buffer_size"],
            "avg_fct_slowdown":        res["avg"],
            "p99_fct_slowdown":        res["p99"],
            "flow_size_buckets_bytes": res["size"],
        })

    if not out["data_series"]:
        print(f"[skip] {os.path.basename(split_path)}: no valid series produced")
        return

    base = os.path.splitext(os.path.basename(split_path))[0]
    json_path = os.path.join(JSON_DIR, f"{base}.json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=4)
    print(f"[ok]  {base}.json  ({len(out['data_series'])} series)")


def main():
    ap = argparse.ArgumentParser(
        description="Parse each split history file into a per-file FCT JSON."
    )
    ap.add_argument("split", nargs="?", default=None,
                    help=f"A single split file or directory (default: {SPLIT_DIR}).")
    ap.add_argument("-sT", dest="time_limit_begin", type=int, default=0)
    ap.add_argument("-fT", dest="time_limit_end", type=int,
                    default=10 ** 18)
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="Number of split files to process in parallel "
                         "(default: 1, serial). Use 0 to auto-detect CPU count.")
    args = ap.parse_args()

    target = args.split or SPLIT_DIR
    if os.path.isfile(target):
        files = [target]
    elif os.path.isdir(target):
        files = sorted(glob.glob(os.path.join(target, "*.txt")))
    else:
        print(f"ERROR: {target} not found", file=sys.stderr)
        sys.exit(1)

    os.makedirs(JSON_DIR, exist_ok=True)
    print(f"Output dir: {JSON_DIR}")
    print(f"Processing {len(files)} split file(s)...")

    jobs = os.cpu_count() if args.jobs == 0 else max(1, args.jobs)

    if jobs == 1 or len(files) == 1:
        for p in files:
            print(f"-- {os.path.basename(p)}")
            process_split_file(p, args.time_limit_begin, args.time_limit_end)
        return

    print(f"Using {jobs} worker(s)")
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        future_to_file = {
            ex.submit(
                process_split_file,
                p,
                args.time_limit_begin,
                args.time_limit_end,
            ): p
            for p in files
        }

        for fut in as_completed(future_to_file):
            p = future_to_file[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"[fail] {os.path.basename(p)}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
