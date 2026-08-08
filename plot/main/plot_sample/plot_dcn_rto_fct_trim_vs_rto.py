import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from collections import defaultdict

plt.rcParams["font.family"] = "DejaVu Sans"
FONT_FAMILY = "DejaVu Sans"

try:
    import lib.py.plot.plot as plot
except ImportError:
    pass


TRIM_RECOVERIES = {"IdealTrimming", "IdealTrimming+slowstart"}
RTO_RECOVERIES = {"RTO+GBN", "RTO+GBN+slowstart", "RTO+GBN+Now"}
COMBINED_LBS = ["RPS", "AR", "DRILLGroup", "SGLB"]


def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num:.0f}"
    if num < 1000000:
        return f"{num / 1000:.0f}K"
    return f"{num / 1000000:.1f}M"


def get_visible_xticks(x_tick_positions, x_tick_labels):
    visible_indices = [i for i in range(len(x_tick_labels))
                       if i % 2 == 0 or i == len(x_tick_labels) - 1]
    visible_positions = [x_tick_positions[i] for i in visible_indices]
    visible_labels = [format_bytes(x_tick_labels[i]) for i in visible_indices]
    return visible_positions, visible_labels


def _nice_integer_top(x):
    if x <= 5:
        return max(1, int(np.ceil(x)))
    if x <= 10:
        for top in (10,):
            if top >= x:
                return top
    elif x <= 30:
        for top in (15, 20, 30):
            if top >= x:
                return top
    else:
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

    min_bottom_gap = 2 if bottom < 10 else 3
    if (ymin - bottom) <= min_bottom_gap:
        candidate = bottom
        while candidate > 1 and (ymin - candidate) <= min_bottom_gap:
            next_candidate = _nice_integer_bottom(candidate - 1)
            if next_candidate >= candidate:
                break
            candidate = next_candidate
        if candidate < bottom:
            bottom = candidate
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
    if len(interior_ticks) > 3:
        step = int(np.ceil(len(interior_ticks) / 3))
        interior_ticks = interior_ticks[::step][:3]
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


def place_legend(ax, max_rows):
    handles, labels = ax.get_legend_handles_labels()
    n_items = len(labels)
    ncol = max(1, int(np.ceil(n_items / max_rows))) if max_rows > 0 else 1
    ax.legend(
        handles,
        labels,
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


def get_label(s, include_lb=False):
    rec = s.get("recovery_mechanism", "N/A")
    lb = s.get("load_balancing_mode", "N/A")
    if str(lb).lower() == "drillgroup":
        lb = "DRILL"
    rec_lower = str(rec).lower()
    if "idealtrimming" in rec_lower:
        label = "Trim"
    elif "rto+gbn" in rec_lower:
        label = ""
    else:
        label = str(rec)
    if include_lb:
        return f"{lb}({label})" if label else str(lb)
    return label or str(lb)


def draw_compare(series_list, x_tick_labels, output_prefix, include_lb=False, legend_max_rows=99):
    if not series_list:
        return
    x_tick_positions = np.arange(len(x_tick_labels))
    visible_xticks, visible_xtick_labels = get_visible_xticks(x_tick_positions, x_tick_labels)
    gamma = 0.001

    for metric, ylabel, suffix in [
        ("avg_fct_slowdown", "Average FCT Slowdown", "avg"),
        ("p99_fct_slowdown", "P99 FCT Slowdown", "p99"),
    ]:
        p = plot.LinePointPlot()
        p.fig.set_size_inches(9.6, 6.0)
        y_values = []
        for s in series_list:
            y = s.get(metric)
            if not y:
                continue
            if len(y) != len(x_tick_positions):
                print(f"⚠️ Warning: point count mismatch for {get_label(s, include_lb)}; skipping.")
                continue
            y_values.extend(y)
            p.plot(x_tick_positions, y, label=get_label(s, include_lb), markevery=1)

        p.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
        p.ax.set_ylabel(ylabel, fontsize=35)
        p.ax.set_yscale(
            "function",
            functions=(lambda x: np.power(x, gamma),
                       lambda y: np.power(y, 1 / gamma)),
        )
        apply_y_axis_bounds(p.ax, y_values)
        p.ax.set_xticks(visible_xticks)
        p.ax.set_xticklabels(
            visible_xtick_labels, rotation=45, ha="center", fontsize=30,
            fontweight="semibold", rotation_mode="anchor"
        )
        p.ax.set_xlim(x_tick_positions[0] - 0.5, x_tick_positions[-1] + 0.5)
        p.ax.tick_params(axis="x", which="major", direction="out", length=8, pad=10, colors="black")
        p.ax.tick_params(axis="x", which="minor", direction="out", colors="black")
        p.ax.tick_params(axis="y", which="major", labelsize=30, colors="black")
        p.ax.tick_params(axis="y", which="minor", colors="black")
        style_axes(p.ax)
        place_legend(p.ax, legend_max_rows)
        out_path = f"{output_prefix}_{suffix}.pdf"
        plt.savefig(out_path, bbox_inches="tight")
        plt.close()
        print(f"  saved: {out_path}")


def draw_trim_vs_rto(json_path, output_dir, no_drill_trim=False, no_sglb_trim=False,
                     legend_max_rows=99):
    meta = os.path.basename(json_path)
    if "FC_Lossy" not in meta:
        print(f"skip (not Lossy): {meta}")
        return

    with open(json_path) as f:
        data = json.load(f)
    series_all = data.get("data_series", [])
    if not series_all:
        print(f"{json_path}: empty")
        return

    x_tick_labels = series_all[0]["flow_size_buckets_bytes"]
    base = os.path.splitext(os.path.basename(json_path))[0]

    keep = [s for s in series_all
            if s.get("recovery_mechanism") in TRIM_RECOVERIES | RTO_RECOVERIES]
    if no_drill_trim:
        keep = [
            s for s in keep
            if not (
                str(s.get("load_balancing_mode", "")).lower() == "drillgroup"
                and "idealtrimming" in str(s.get("recovery_mechanism", "")).lower()
            )
        ]
    if no_sglb_trim:
        keep = [
            s for s in keep
            if not (
                str(s.get("load_balancing_mode", "")).upper() == "SGLB"
                and "idealtrimming" in str(s.get("recovery_mechanism", "")).lower()
            )
        ]
    if not keep:
        print(f"{base}: no trim/RTO+GBN series")
        return

    per_lb = defaultdict(list)
    for s in keep:
        per_lb[s.get("load_balancing_mode", "N/A")].append(s)

    combined = []
    for lb in COMBINED_LBS:
        combined.extend(per_lb.get(lb, []))
    if combined:
        print(f"{base} [combined {'+'.join(COMBINED_LBS)}]: {len(combined)} series")
        prefix = os.path.join(output_dir, f"{base}_LBCombined_TrimVsRtoGbn")
        draw_compare(
            combined,
            x_tick_labels,
            prefix,
            include_lb=True,
            legend_max_rows=legend_max_rows,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path")
    ap.add_argument("-o", "--output_dir", default=None,
                    help="Output dir (default: same as input).")
    ap.add_argument("--no-drill-trim", action="store_true",
                    help="Exclude DRILL(Trim) series.")
    ap.add_argument("--no-sglb-trim", action="store_true",
                    help="Exclude SGLB(Trim) series.")
    ap.add_argument("--legend-max-rows", type=int, default=99,
                    help="Maximum legend entries per column before adding another column.")
    args = ap.parse_args()

    path = os.path.abspath(os.path.expanduser(args.input_path))
    if os.path.isfile(path):
        out_dir = args.output_dir or os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)
        draw_trim_vs_rto(
            path,
            out_dir,
            no_drill_trim=args.no_drill_trim,
            no_sglb_trim=args.no_sglb_trim,
            legend_max_rows=args.legend_max_rows,
        )
    else:
        out_dir = args.output_dir or path
        os.makedirs(out_dir, exist_ok=True)
        for f in glob.glob(os.path.join(path, "*.json")):
            draw_trim_vs_rto(
                f,
                out_dir,
                no_drill_trim=args.no_drill_trim,
                no_sglb_trim=args.no_sglb_trim,
                legend_max_rows=args.legend_max_rows,
            )


if __name__ == "__main__":
    main()
