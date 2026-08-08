#!/usr/bin/env python3
"""
Parse AR Retx w/ Drop and AR Retx Spurious from _out_flow_drop.txt
for every entry in a history file, and produce a trace CSV + summary.
Field parsing follows parse_dcn_rto_fct.py exactly.
"""

import os
import sys
import csv
import re
from collections import defaultdict

cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR",
    6: "LetFlow", 7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}

topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000, "leaf_spine_L8_S16_100G_OS1": 104000,
    "leaf_spine_L2_S4_100G_OS1": 104000, "leaf_spine_L16_S16_100G_OS1": 104000,
    "fat_k8_100G_OS2": 153000, "fat_k8_100G_OS1": 153000,
    "leafspine_L8_S16_100G_AsymFail1pct_OS1": 104000,
    "leafspine_L8_S16_100G_AsymFail10pct_OS1": 104000,
    "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1": 104000,
    "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1": 104000,
}

OUTPUT_ROOT = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                           "../mix/output")


def parse_drop_file(path):
    retx_drop = None
    retx_spurious = None
    try:
        with open(path) as f:
            for line in f:
                m = re.search(r'AR Retx w/ Drop\s*:\s*(\d+)', line)
                if m:
                    retx_drop = int(m.group(1))
                m = re.search(r'AR Retx Spurious\s*:\s*(\d+)', line)
                if m:
                    retx_spurious = int(m.group(1))
    except FileNotFoundError:
        pass
    return retx_drop, retx_spurious


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <history_file>")
        sys.exit(1)

    history_file = sys.argv[1]
    out_dir = os.path.dirname(os.path.realpath(history_file))
    base = os.path.splitext(os.path.basename(history_file))[0]
    trace_csv   = os.path.join(out_dir, f"{base}_retrans_trace.csv")
    summary_txt = os.path.join(out_dir, f"{base}_retrans_summary.txt")

    rows = []
    missing = []

    with open(history_file) as f:
        for line in f:
            # only process config lines (must contain a known topo prefix)
            matched_topo = None
            for topo_prefix in topo2bdp:
                if topo_prefix in line:
                    matched_topo = topo_prefix
                    break
            if not matched_topo:
                continue

            parsed = line.strip().split(',')
            if len(parsed) < 24:
                continue

            try:
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                irn        = int(parsed[11])
            except ValueError:
                continue

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

            # --- recovery_label: same logic as parse_dcn_rto_fct.py ---
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

            lb_str  = lb_modes[lb_mode_id]
            cc_str  = cc_modes[cc_mode_id]
            fc_str  = "Lossless" if pfc == 1 else "Lossy"

            drop_file = os.path.join(OUTPUT_ROOT, config_id,
                                     f"{config_id}_out_flow_drop.txt")
            retx_drop, retx_spur = parse_drop_file(drop_file)

            if retx_drop is None or retx_spur is None:
                missing.append(config_id)
                retx_drop = retx_spur = 0

            total      = retx_drop + retx_spur
            spur_ratio = retx_spur / total if total > 0 else 0.0

            rows.append({
                "config_id":      config_id,
                "topo":           topo,
                "load_type":      load_type,
                "netload":        netload,
                "flow_control":   fc_str,
                "error_rate":     error_rate,
                "cc":             cc_str,
                "lb":             lb_str,
                "recovery":       recovery_label,
                "timeout_mode":   timeout_mode,
                "rto_high":       rto_high,
                "rto_low":        rto_low,
                "retx_w_drop":    retx_drop,
                "retx_spurious":  retx_spur,
                "retx_total":     total,
                "spurious_ratio": round(spur_ratio, 6),
            })

    # --- trace CSV ---
    fields = ["config_id", "topo", "load_type", "netload", "flow_control",
              "error_rate", "cc", "lb", "recovery", "timeout_mode",
              "rto_high", "rto_low",
              "retx_w_drop", "retx_spurious", "retx_total", "spurious_ratio"]
    with open(trace_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Trace CSV  -> {trace_csv}  ({len(rows)} entries)")

    # --- grouped summary ---
    # group by (topo, load_type, netload, flow_control, error_rate, lb, recovery, rto_high, rto_low)
    groups = defaultdict(lambda: {"retx_w_drop": 0, "retx_spurious": 0, "retx_total": 0, "n": 0})
    for r in rows:
        key = (r["topo"], r["load_type"], r["netload"], r["flow_control"],
               r["error_rate"], r["lb"], r["recovery"], r["rto_high"], r["rto_low"])
        g = groups[key]
        g["retx_w_drop"]   += r["retx_w_drop"]
        g["retx_spurious"] += r["retx_spurious"]
        g["retx_total"]    += r["retx_total"]
        g["n"]             += 1

    W = 110
    hdr = (f"{'TOPO':<40} {'LOAD_TYPE':>14} {'LB':>6} {'RECOVERY':>18} "
           f"{'RTO_H':>6} {'RTO_L':>6} {'DROP':>10} {'SPUR':>10} {'TOTAL':>10} {'SPUR%':>7}")
    lines = ["=" * W, hdr, "=" * W]

    for key, g in sorted(groups.items()):
        topo, load_type, netload, fc, err, lb, recovery, rto_h, rto_l = key
        total = g["retx_total"]
        spur  = g["retx_spurious"]
        drop  = g["retx_w_drop"]
        ratio = spur / total * 100 if total > 0 else 0.0
        lines.append(
            f"{topo:<40} {load_type:>14} {lb:>6} {recovery:>18} "
            f"{rto_h:>6} {rto_l:>6} {drop:>10} {spur:>10} {total:>10} {ratio:>6.1f}%"
        )
    lines.append("=" * W)

    if missing:
        lines.append(f"\nMissing drop files ({len(missing)}): {', '.join(missing[:10])}"
                     + (" ..." if len(missing) > 10 else ""))

    summary = "\n".join(lines)
    with open(summary_txt, 'w') as f:
        f.write(summary + "\n")
    print(f"Summary    -> {summary_txt}")
    print()
    print(summary)


if __name__ == "__main__":
    main()
