"""Compare AR(RTO+GBN) FCT slowdown across different buffer sizes, for the
same topology and bandwidth. Each output figure has one line per buffer size.

Input: directory containing DATA_TOPO_<topo>_<bw>_OS1_FC_<fc>_BUF_<bufsz>.json
       files produced by the FCT parser.
"""

import argparse
import glob
import json
import os
import re
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import math

try:
    import lib.py.plot.plot as plot
except ImportError:
    pass


FONT_FAMILY = "DejaVu Sans"
plt.rcParams["font.family"] = FONT_FAMILY


# Matches the parser's file naming convention.
FNAME_RE = re.compile(
    r"DATA_TOPO_(?P<topo>.+?)_(?P<bw>\d+G)_OS\d+_FC_(?P<fc>\w+?)_BUF_(?P<buf>[\d.]+)\.json$"
)

DEFAULT_BUFSZ = ["0.32", "0.44", "1.92"]


def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num:.0f}"
    if num < 1000000:
        return f"{num / 1000:.0f}K"
    return f"{num / 1000000:.1f}M"


def _nice_integer_top(x):
    if x <= 5:
        return max(1, int(np.ceil(x)))
    if x <= 10:
        return 10
    if x <= 30:
        for top in (15, 20, 30):
            if top >= x:
                return top
    step = 10 if x <= 100 else 50
    return int(np.ceil(x / step) * step)


def _nice_integer_bottom(x):
    if x <= 1:
        return 1
    if x <= 5:
        return max(1, int(np.floor(x)))
    if x <= 8:
        return 5
    if x < 10:
        return 8
    if x < 15:
        return 10
    if x < 20:
        return 15
    if x < 30:
        return 20
    step = 10 if x <= 100 else 50
    return int(np.floor(x / step) * step)


def apply_y_axis_bounds(ax, y_values):
    values = [float(v) for v in y_values if np.isfinite(v) and v > 0]
    if not values:
        return

    ymin = min(values)
    ymax = max(values)
    bottom = _nice_integer_bottom(ymin * 0.98)
    top = _nice_integer_top(ymax * 1.08)
    if top <= bottom:
        top = bottom + 1

    ax.set_ylim(bottom=bottom, top=top)
    interior_ticks = [tick for tick in ax.get_yticks() if bottom < tick < top]
    span = top - bottom
    edge_gap = max(span * 0.12, 1)
    interior_ticks = [
        tick for tick in interior_ticks
        if (tick - bottom) >= edge_gap and (top - tick) >= edge_gap
    ]
    if len(interior_ticks) > 5:
        step = int(np.ceil(len(interior_ticks) / 5))
        interior_ticks = interior_ticks[::step][:5]
    ticks = [bottom] + interior_ticks + [top]
    ax.set_yticks(ticks)


def style_axes(ax):
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_size(35)
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_size(35)
    ax.tick_params(axis="both", which="both", colors="black", labelsize=30)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(FONT_FAMILY)
        label.set_color("black")
    for spine in ax.spines.values():
        spine.set_color("black")


def place_legend(ax):
    legend = ax.legend(
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        loc="best",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
        borderpad=0.18,
        labelspacing=0.15,
        columnspacing=0.45,
        handlelength=1.4,
        handletextpad=0.2,
    )
    legend.set_zorder(100)
    return legend


def _norm_buf(s):
    # Normalize "0.31" and "0.32" style strings for equality.
    try:
        return f"{float(s):.2f}"
    except (TypeError, ValueError):
        return str(s)


def _pick_series(data, lb, recovery):
    """Return first series matching (lb, recovery), or None."""
    for s in data.get("data_series", []):
        if (str(s.get("load_balancing_mode", "")).upper() == lb.upper()
                and str(s.get("recovery_mechanism", "")) == recovery):
            return s
    return None


def _group_files(input_dir, bw_filter, topo_filter, bufsz_list):
    """{(topo, bw, fc): {norm_buf: path}}"""
    wanted = {_norm_buf(b) for b in bufsz_list}
    groups = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(input_dir, "*.json"))):
        m = FNAME_RE.search(os.path.basename(path))
        if not m:
            continue
        topo = m.group("topo")
        bw = m.group("bw")
        fc = m.group("fc")
        buf = _norm_buf(m.group("buf"))
        if bw_filter and bw != bw_filter:
            continue
        if topo_filter and topo_filter not in topo:
            continue
        if buf not in wanted:
            continue
        groups[(topo, bw, fc)][buf] = path
    return groups


def _bw_display(bw):
    m = re.match(r"(\d+)\s*G", str(bw))
    return f"{m.group(1)}Gbps" if m else str(bw)


def draw_group(topo, bw, fc, buf_to_path, bufsz_order, lb, recovery,
               output_dir, label_suffix):
    x_labels = None
    per_buf_series = {}
    for buf in bufsz_order:
        path = buf_to_path.get(buf)
        if not path:
            print(f"  [skip] buf={buf}: no file")
            continue
        with open(path) as f:
            data = json.load(f)
        s = _pick_series(data, lb, recovery)
        if not s:
            print(f"  [skip] buf={buf}: {lb}/{recovery} not in {os.path.basename(path)}")
            continue
        if x_labels is None:
            x_labels = s.get("flow_size_buckets_bytes")
        per_buf_series[buf] = s

    if not per_buf_series or not x_labels:
        print(f"  [WARN] nothing to plot for {topo}/{bw}/{fc}")
        return

    x_positions = list(range(len(x_labels)))
    xtick_labels_shown = [
        format_bytes(x) if i % 2 == 0 or i == len(x_labels) - 1 else ""
        for i, x in enumerate(x_labels)
    ]
    gamma = 0.001
    rec_display = recovery.replace("RTO+GBN+Now", "RTO+GBN") \
                          .replace("IdealTrimming", "Packet-trimming")

    for metric, ylabel, suffix in [
        ("avg_fct_slowdown", "Average FCT Slowdown", "avg"),
        ("p99_fct_slowdown", "P99 FCT Slowdown",     "p99"),
    ]:
        p = plot.LinePointPlot()
        p.fig.set_size_inches(9.6, 6.0)
        y_values = []
        for buf in bufsz_order:
            s = per_buf_series.get(buf)
            if not s:
                continue
            y = s.get(metric)
            if not y:
                continue
            y_values.extend(y)
            num = len(y)
            mark_every = list(range(0, num, 2))
            if num - 1 not in mark_every:
                mark_every.append(num - 1)
            p.plot(x_positions, y,
                   label=f"{buf}MB/{_bw_display(bw)}",
                   markevery=mark_every)

        p.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
        p.ax.set_ylabel(ylabel, fontsize=35)
        p.ax.set_yscale(
            "function",
            functions=(lambda x: np.power(x, gamma),
                       lambda y: np.power(y, 1 / gamma)),
        )
        apply_y_axis_bounds(p.ax, y_values)
        p.ax.set_xticks(x_positions)
        p.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha="center", fontsize=30)
        p.ax.tick_params(axis="x", which="major", direction="out", length=8, pad=10, colors="black")
        p.ax.tick_params(axis="x", which="minor", direction="out", colors="black")
        p.ax.tick_params(axis="y", which="major", colors="black")
        p.ax.tick_params(axis="y", which="minor", colors="black")
        style_axes(p.ax)
        legend = place_legend(p.ax)
        legend.set_title(f"{lb}({rec_display})")
        legend.get_title().set_fontfamily(FONT_FAMILY)
        legend.get_title().set_color("black")
        legend.get_title().set_size(25)

        name_parts = [lb, rec_display.replace("+", ""), topo, bw, fc, "bufsz"]
        if label_suffix:
            name_parts.append(label_suffix)
        out_path = os.path.join(output_dir,
                                "_".join(name_parts) + f"_{suffix}.pdf")
        plt.savefig(out_path, bbox_inches="tight")
        plt.close()
        print(f"  saved: {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path",
                    help="Directory containing DATA_TOPO_*_BUF_*.json files.")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="Output directory (defaults to input_path).")
    ap.add_argument("--bufsz", nargs="+", default=DEFAULT_BUFSZ,
                    help=f"Buffer sizes to include as lines "
                         f"(default: {' '.join(DEFAULT_BUFSZ)}).")
    ap.add_argument("--bw", default=None,
                    help="Filter by bandwidth, e.g. 400G. "
                         "Omit to plot every bandwidth present.")
    ap.add_argument("--topo", default=None,
                    help="Substring filter on topology "
                         "(e.g. 'fat_k8' or 'leaf_spine').")
    ap.add_argument("--lb", default="AR",
                    help="Load-balancing mode to pick (default: AR).")
    ap.add_argument("--recovery", default="RTO+GBN+Now",
                    help="Recovery mechanism to pick "
                         "(default: RTO+GBN+Now; displayed as RTO+GBN).")
    ap.add_argument("--label-suffix", default=None,
                    help="Optional suffix appended to output filenames.")
    args = ap.parse_args()

    input_dir = os.path.abspath(os.path.expanduser(args.input_path))
    if not os.path.isdir(input_dir):
        print(f"Error: not a directory: {input_dir}")
        return
    output_dir = args.output_dir or input_dir
    os.makedirs(output_dir, exist_ok=True)

    bufsz_order = [_norm_buf(b) for b in args.bufsz]

    groups = _group_files(input_dir, args.bw, args.topo, bufsz_order)
    if not groups:
        print("No matching files.")
        return

    for (topo, bw, fc), buf_to_path in sorted(groups.items()):
        print(f"--- {topo} | {bw} | {fc} ---")
        draw_group(topo, bw, fc, buf_to_path, bufsz_order,
                   args.lb, args.recovery, output_dir, args.label_suffix)


if __name__ == "__main__":
    main()
