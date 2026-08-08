#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Batch-plot per-QP rate-over-time for every run listed in a history file.

Each matching history line is looked up at
    mix/output/<config_id>/<config_id>_out_rate.txt
and rendered as a figure with the top-N longest-lived flows.

Usage:
    python3 parse_qp_rate.py /path/to/for_rate_ana.txt
    python3 parse_qp_rate.py ... --topn 10 --metric send --jobs 8 --ymax 100
"""

import argparse
import multiprocessing as mp
import os
import traceback
from functools import partial

from plot_qp_rate_top10 import (
    QP_KEY,
    load_rate_file,
    parse_rank_range,
    pick_longest_lived,
    pick_rank_range,
    plot_rate,
)


cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none",
    5: "dcqcn_lane", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR",
    6: "LetFlow", 7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}

TOPO_PREFIXES = [
    "leaf_spine_L2_S8_100G_OS1", "bigswitch_H16_100G_OS1",
    "leaf_spine_128_100G_OS2", "leaf_spine_L8_S16_100G_OS1",
    "leaf_spine_L2_S4_100G_OS1", "leaf_spine_L16_S16_100G_OS1",
    "leaf_spine_L8_S8_400G_OS2", "leaf_spine_L8_S16_400G_OS1",
    "fat_k8_400G_OS1", "fat_k8_100G_OS2", "fat_k8_100G_OS1",
    "three_layer_p4_tor4_l19_l28_s8_nofail_OS1",
    "three_layer_p4_tor4_l19_l28_s8_faill1_OS1",
    "three_layer_p4_tor4_l19_l28_s8_faill2_OS1",
    "three_layer_p4_tor4_l19_l28_s8_faill12_OS1",
    "three_layer_p4_tor4_l19_l24_s8_faill23_OS1",
    "three_layer_p4_tor4_l19_l28_s8_failhalf_OS1",
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2",
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2",
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2",
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2",
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1",
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1",
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1",
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1",
    "leafspine_L8_S16_100G_AsymFail1pct_OS1",
    "leafspine_L8_S16_100G_AsymFail10pct_OS1",
    "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1",
    "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1",
]


def get_file_path():
    return os.path.dirname(os.path.realpath(__file__))


def parse_history_line(line: str):
    parsed = line.strip().split(",")
    if len(parsed) < 24:
        return None
    if parsed[15] not in TOPO_PREFIXES:
        if not any(t in line for t in TOPO_PREFIXES):
            return None

    try:
        cc_id = int(parsed[2])
        lb_id = int(parsed[3])
        irn = int(parsed[11])
    except ValueError:
        return None

    if cc_id not in cc_modes or lb_id not in lb_modes or irn not in irn_modes:
        return None

    ar_mode = parsed[4]
    timeout_mode = parsed[21]

    recovery = irn_modes[irn]
    if ar_mode == "1":
        if irn in (0, 1):
            recovery = "RTO+GBN"
        elif irn == 2:
            recovery = "IdealTrimming"
    if timeout_mode == "1":
        if recovery == "RTO+GBN":
            recovery = "RTO+GBN+slowstart"
        elif recovery == "IdealTrimming":
            recovery = "IdealTrimming+slowstart"
        elif recovery == "Ideal":
            recovery = "Ideal+slowstart"
    elif timeout_mode == "2":
        if recovery == "RTO+GBN":
            recovery = "RTO+GBN+Now"

    return {
        "config_id": parsed[1],
        "cc": cc_modes[cc_id],
        "lb": lb_modes[lb_id],
        "recovery": recovery,
        "pfc": int(parsed[10]),
        "window_size": parsed[14],
        "topo": parsed[15],
        "bw": parsed[16],
        "load_type": parsed[17],
        "netload": parsed[18],
        "error_rate": parsed[19],
        "rto_high": parsed[22],
        "rto_low": parsed[23],
    }


def process_entry(entry, mix_output_dir, out_dir, topn, rank_range, metrics, ymax, keep_negative, smooth):
    """Worker: load rate file once, render one figure per requested metric."""
    cid = entry["config_id"]
    rate_file = os.path.join(mix_output_dir, cid, f"{cid}_out_rate.txt")
    if not os.path.exists(rate_file):
        return (cid, 0, f"skip: rate file not found ({rate_file})")

    try:
        df = load_rate_file(rate_file, drop_negative=not keep_negative)
    except Exception as e:
        return (cid, 0, f"skip: load failed — {e!r}\n{traceback.format_exc()}")

    if df.empty:
        return (cid, 0, "skip: empty rate file")

    if rank_range is not None:
        start, end = rank_range
        keys = pick_rank_range(df, start, end)
        rank_tag = f"rank{start}-{end}"
        rank_desc = f"Rank {start}-{start + len(keys) - 1} QPs"
    else:
        keys = pick_longest_lived(df, topn)
        rank_tag = f"top{topn}"
        rank_desc = f"Top-{len(keys)} QPs"
    fc = "Lossless" if entry["pfc"] == 1 else "Lossy"
    tag = (
        f"{cid}_{entry['topo']}_L{entry['netload']}_{fc}_{entry['load_type']}"
        f"_{entry['cc']}_{entry['lb']}_{entry['recovery']}"
    ).replace("/", "_").replace(" ", "_")

    ok = 0
    smooth_suffix = f"_smooth{smooth}" if smooth and smooth > 1 else ""
    for metric in metrics:
        out_path = os.path.join(
            out_dir, f"rate_{rank_tag}_{metric}{smooth_suffix}_{tag}.pdf"
        )
        title = (
            f"{rank_desc} ({metric}{', smooth=' + str(smooth) if smooth > 1 else ''}) — "
            f"{entry['topo']} {fc} L{entry['netload']}% {entry['load_type']}\n"
            f"cc={entry['cc']} lb={entry['lb']} recovery={entry['recovery']} "
            f"(rto_h={entry['rto_high']}us rto_l={entry['rto_low']}us) id={cid}"
        )
        try:
            plot_rate(df, keys, metric, out_path, title, ymax=ymax, smooth=smooth)
            ok += 1
        except Exception as e:
            print(f"[err] {cid} metric={metric}: {e!r}")
    return (cid, ok, f"rows={len(df)} qps={df.groupby(QP_KEY).ngroups}")


def main():
    ap = argparse.ArgumentParser(
        description="Parse a history file and plot QP rate curves for each run"
    )
    ap.add_argument("history_file")
    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--range", dest="rank_range", default=None,
                    help="rank range 'A-B' (1-indexed, inclusive); overrides --topn")
    ap.add_argument("--metric", choices=["send", "target", "both"], default="send")
    ap.add_argument("--output_dir", default=None)
    ap.add_argument("--mix_output_dir", default=None)
    ap.add_argument("--jobs", "-j", type=int, default=0,
                    help="parallel workers; 0 = min(cpu_count, 8), 1 = sequential")
    ap.add_argument("--ymax", type=float, default=100.0,
                    help="y-axis upper bound in Gb/s; 0 disables (default: 100)")
    ap.add_argument("--keep_negative", action="store_true",
                    help="keep negative rate samples (default: drop, since GBN rewinds snd_nxt)")
    ap.add_argument("--smooth", type=int, default=1,
                    help="rolling-mean window in samples (1 disables, default: 1)")
    args = ap.parse_args()

    script_dir = get_file_path()
    mix_output_dir = args.mix_output_dir or os.path.join(script_dir, "../mix/output")
    out_dir = args.output_dir or os.path.join(script_dir, "plots_qp_rate")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[info] history: {args.history_file}")
    print(f"[info] mix/output: {mix_output_dir}")
    print(f"[info] output dir: {out_dir}")

    seen = set()
    entries = []
    with open(args.history_file) as f:
        for line in f:
            entry = parse_history_line(line)
            if entry is None:
                continue
            if entry["config_id"] in seen:
                continue
            seen.add(entry["config_id"])
            entries.append(entry)

    print(f"[info] {len(entries)} unique runs to process")
    if not entries:
        return

    metrics = ["send", "target"] if args.metric == "both" else [args.metric]
    ymax = args.ymax if args.ymax and args.ymax > 0 else None
    rank_range = parse_rank_range(args.rank_range) if args.rank_range else None

    jobs = args.jobs or min(mp.cpu_count(), 8)
    jobs = max(1, min(jobs, len(entries)))
    print(f"[info] workers: {jobs}")

    worker = partial(
        process_entry,
        mix_output_dir=mix_output_dir,
        out_dir=out_dir,
        topn=args.topn,
        rank_range=rank_range,
        metrics=metrics,
        ymax=ymax,
        keep_negative=args.keep_negative,
        smooth=args.smooth,
    )

    total_ok = 0
    if jobs == 1:
        for entry in entries:
            cid, ok, note = worker(entry)
            total_ok += ok
            print(f"[{cid}] {note} -> {ok} figs")
    else:
        # imap_unordered streams results so progress prints don't stall behind
        # the slowest run; chunksize=1 keeps load-balance even for uneven files.
        with mp.Pool(jobs) as pool:
            for cid, ok, note in pool.imap_unordered(worker, entries, chunksize=1):
                total_ok += ok
                print(f"[{cid}] {note} -> {ok} figs")

    print(f"[done] wrote {total_ok} figures to {out_dir}")


if __name__ == "__main__":
    main()
