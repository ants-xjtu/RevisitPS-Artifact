#!/usr/bin/python3
"""
Compare AR(RTO+GBN) Average/Normalized CCT across buffer sizes.

For a given topology + flow_control, merges JCT_VS_GROUPSIZE_*_BUF_*.json
files (one per buffer size and load_type) and draws ONE grouped bar chart:
  - x-axis  : AlltoAll, RingAllreduce, AlltoAllV-{8,16,32,64,128}
  - bars    : one per buffer size (default 0.32, 0.44, 1.92 MB)
  - series  : fixed to (load_balancing_mode, recovery_mechanism) = AR/RTO+GBN
              (congestion_control = DCQCN by default)
"""

import argparse
import glob
import json
import math
import os
import re

import matplotlib.pyplot as plt
import numpy as np

import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"


# Same x-axis schema as plot_sim_ai_jct_avg.py.
COMBINED_CATEGORIES = [
    ("Alltoall",      8,   "AlltoAll"),
    ("RingAllreduce", 8,   "RingAllreduce"),
    ("AlltoallV",     8,   "AlltoAllV-8"),
    ("AlltoallV",     16,  "AlltoAllV-16"),
    ("AlltoallV",     32,  "AlltoAllV-32"),
    ("AlltoallV",     64,  "AlltoAllV-64"),
    ("AlltoallV",     128, "AlltoAllV-128"),
]

DEFAULT_BUFSZ = ["0.32", "0.44", "1.92"]

FNAME_BUF_RE = re.compile(r"_BUF_([\d.]+)\.json$")


def _norm_buf(s):
    try:
        return f"{float(s):.2f}"
    except (TypeError, ValueError):
        return str(s)


def _nice_top(x):
    if x <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(x))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= x:
            return m * exp
    return 10 * exp


def _nice_step(x):
    if x <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= x:
            return m * exp
    return 10 * exp


def _apply_plot_style(ax, legend=None):
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.tick_params(axis="both", which="both", colors="black")
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("black")
        label.set_fontfamily(FONT_FAMILY)
    for spine in ax.spines.values():
        spine.set_color("black")
    ax.grid(False, axis="x")
    ax.grid(True, axis="y")
    if legend is not None:
        legend.get_frame().set_edgecolor("dimgray")
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_alpha(1.0)
        for txt in legend.get_texts():
            txt.set_fontfamily(FONT_FAMILY)
            txt.set_color("black")
        title = legend.get_title()
        if title is not None:
            title.set_fontfamily(FONT_FAMILY)
            title.set_color("black")


def _bw_display(meta_or_topo):
    m = re.search(r"(\d+)\s*G", str(meta_or_topo))
    return f"{m.group(1)}Gbps" if m else ""


def _topo_family(topo):
    """'fat_k8' or 'leaf_spine_L8_S16' (i.e. drop bandwidth + OS suffixes)."""
    t = re.sub(r"_\d+G(_OS\d+)?$", "", str(topo))
    return t


def _buf_of(path):
    m = FNAME_BUF_RE.search(os.path.basename(path))
    return _norm_buf(m.group(1)) if m else None


def _pick_series(data, lb, recovery, cc):
    """Return the best matching series, or None.

    For recovery='RTO+GBN', matches any RTO+GBN* series (including
    RTO+GBN+1/N variants used in Lossy), preferring a +1/N variant when
    present (Lossy case) and falling back to bare RTO+GBN (Lossless).
    """
    want_rto = recovery.startswith("RTO+GBN")
    candidates = []
    for s in data.get("data_series", []):
        if str(s.get("load_balancing_mode", "")).upper() != lb.upper():
            continue
        if cc and str(s.get("congestion_control", "")) != cc:
            continue
        rec = str(s.get("recovery_mechanism", ""))
        if want_rto:
            if not rec.startswith("RTO+GBN"):
                continue
        else:
            if rec != recovery:
                continue
        candidates.append(s)
    if not candidates:
        return None
    if want_rto:
        # Prefer +1/N variant (timeout_mode != 0).
        for s in candidates:
            if str(s.get("timeout_mode", "0")) not in ("", "0"):
                return s
    return candidates[0]


def _group_files(json_files, bufsz_list):
    """Group input files by (topo_family, flow_control) -> {buf: {load_type: data}}."""
    wanted = {_norm_buf(b) for b in bufsz_list}
    groups = {}
    for path in json_files:
        buf = _buf_of(path)
        if buf is None or buf not in wanted:
            continue
        with open(path) as f:
            data = json.load(f)
        meta = data.get("metadata", {})
        topo_raw = meta.get("topology", "unknown")
        fam = _topo_family(topo_raw)
        bw = _bw_display(topo_raw)
        fc = meta.get("flow_control", "unknown")
        load_type = meta.get("load_type", "unknown")
        key = (fam, bw, fc)
        groups.setdefault(key, {}).setdefault(buf, {})[load_type] = data
    return groups


def draw_one(fam, bw, fc, buf_to_workloads, bufsz_order, lb, recovery, cc,
             output_dir, normalize, raw_ytop, raw_ystep):
    """Build a figure for one (topo_family, fc). Bars = buffer sizes."""
    n_cat = len(COMBINED_CATEGORIES)
    # {buf: [(mean, ideal) | None per category]}
    buf_values = {}
    for buf in bufsz_order:
        row = [None] * n_cat
        wl_map = buf_to_workloads.get(buf, {})
        for i, (lt, gs, _label) in enumerate(COMBINED_CATEGORIES):
            data = wl_map.get(lt)
            if not data:
                continue
            s = _pick_series(data, lb, recovery, cc)
            if not s:
                continue
            for pt in s.get("points", []):
                if pt.get("group_size") != gs:
                    continue
                mean = pt.get("jct_us")
                ideal = pt.get("ideal_jct_us")
                if mean is None:
                    continue
                val = (float(mean), float(ideal) if ideal else None)
                prev = row[i]
                if prev is None or prev[0] > val[0]:
                    row[i] = val
        buf_values[buf] = row

    if not any(any(v is not None for v in row) for row in buf_values.values()):
        print(f"  [WARN] no {lb}/{recovery} data for {fam}/{fc}")
        return

    category_names = [name for (_, _, name) in COMBINED_CATEGORIES]
    p = plot.BarPlot()
    p.total_bar_width = 0.85

    for buf in bufsz_order:
        row = buf_values[buf]
        yvals = []
        for entry in row:
            if entry is None:
                yvals.append(0.0)
                continue
            mean, ideal = entry
            if normalize:
                yvals.append(mean / ideal if ideal else 0.0)
            else:
                yvals.append(mean)
        label = f"{buf}MB/{bw}" if bw else f"{buf}MB"
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=category_names)
    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=26)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=26)
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelsize=18)
    ax.tick_params(axis="y", labelsize=20)

    legend_title = f"{lb}(RTO+GBN)" if recovery == "RTO+GBN" else f"{lb}({recovery})"
    legend = ax.legend(fontsize=18,
                       prop={"family": FONT_FAMILY, "size": 18},
                       loc="best",
                       ncol=1,
                       frameon=True,
                       edgecolor="dimgray",
                       facecolor="white",
                       framealpha=1.0,
                       title=legend_title,
                       title_fontsize=18)
    _apply_plot_style(ax, legend)

    all_vals = []
    for row in buf_values.values():
        for entry in row:
            if entry is None:
                continue
            mean, ideal = entry
            if normalize:
                if ideal:
                    all_vals.append(mean / ideal)
            else:
                all_vals.append(mean)
    if all_vals:
        top = raw_ytop if raw_ytop is not None else _nice_top(max(all_vals) * 1.1)
        if raw_ystep is not None:
            step = raw_ystep
        elif normalize:
            step = None
        else:
            step = _nice_step(top / 9)
        ax.set_ylim(bottom=0, top=top)
        if step is not None:
            ax.set_yticks(np.arange(0, top + step * 0.5, step))
        else:
            ax.set_yticks(np.linspace(0, top, 6))

    rec_tag = recovery.replace("+", "").replace("/", "")
    parts = ["bufsz", fam, fc.lower(), lb, rec_tag,
             "norm" if normalize else "avg"]
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  saved: {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_path",
                    help="Directory containing JCT_VS_GROUPSIZE_*_BUF_*.json.")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="Output dir (defaults to input dir).")
    ap.add_argument("--bufsz", nargs="+", default=DEFAULT_BUFSZ,
                    help=f"Buffer sizes as bars (default: {' '.join(DEFAULT_BUFSZ)}).")
    ap.add_argument("--lb", default="AR",
                    help="Load-balancing mode (default: AR).")
    ap.add_argument("--recovery", default="RTO+GBN",
                    help="Recovery mechanism (default: RTO+GBN).")
    ap.add_argument("--cc", default="DCQCN",
                    help="Congestion control to keep (default: DCQCN; "
                         "pass empty string '' to keep any).")
    ap.add_argument("--normalize", action="store_true",
                    help="Plot Normalized CCT (mean / ideal).")
    ap.add_argument("--bw-label", default="100Gbps",
                    help="Bandwidth string used in legend (default: 100Gbps, "
                         "the per-host NIC rate on these topologies).")
    ap.add_argument("--raw-ytop", type=float, default=None)
    ap.add_argument("--raw-ystep", type=float, default=None)
    args = ap.parse_args()

    input_dir = os.path.abspath(os.path.expanduser(args.input_path))
    if not os.path.isdir(input_dir):
        print(f"Error: not a directory: {input_dir}")
        return
    output_dir = args.output_dir or input_dir
    os.makedirs(output_dir, exist_ok=True)

    json_files = sorted(glob.glob(os.path.join(input_dir, "JCT_VS_GROUPSIZE_*.json")))
    if not json_files:
        print(f"No JCT_VS_GROUPSIZE_*.json files in {input_dir}")
        return

    bufsz_order = [_norm_buf(b) for b in args.bufsz]
    cc = args.cc or None
    groups = _group_files(json_files, bufsz_order)
    if not groups:
        print("No matching files for the requested buffer sizes.")
        return

    for (fam, bw, fc), buf_to_wl in sorted(groups.items()):
        print(f"--- {fam} | {bw} | {fc} ---")
        draw_one(fam, args.bw_label or bw, fc, buf_to_wl, bufsz_order,
                 args.lb, args.recovery, cc, output_dir,
                 args.normalize, args.raw_ytop, args.raw_ystep)

    print("Done.")


if __name__ == "__main__":
    main()
