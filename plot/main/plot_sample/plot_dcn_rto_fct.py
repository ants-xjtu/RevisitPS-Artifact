import argparse
import json
import re
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
import os
import glob
from collections import defaultdict


plt.rcParams["font.family"] = "DejaVu Sans"

_W_SUFFIX_RE = re.compile(r"\s*W:\S+\s*$")


def _strip_w(s):
    return _W_SUFFIX_RE.sub("", str(s)) if s is not None else s


LB_ORDER = ["ECMP", "Letflow" ,"CONGA" ,"CONWEAVE", "AR"]


def _lb_sort_key(series):
    lb = _strip_w(series.get("load_balancing_mode", "")).upper()
    if lb == "DRILLGROUP":
        lb = "DRILL"
    rec_lower = str(series.get("recovery_mechanism", "")).lower()
    subrank = 0
    if lb == "AR":
        if rec_lower == "idealtrimming+slowstart":
            subrank = 0
        elif rec_lower == "idealtrimming":
            subrank = 1
    try:
        return (LB_ORDER.index(lb), subrank)
    except ValueError:
        return (len(LB_ORDER), subrank, lb)

try:
    import lib.py.plot.plot as plot
except ImportError:
    print("⚠️ Warning: Could not import lib.py.plot.plot. Plotting functions might fail.")
    pass


def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num / 1000:.1f}K"
    elif num < 10000:
        return f"{num / 1000:.1f}K"
    elif num < 1000000:
        return f"{num / 1000:.0f}K"
    else:
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
    top = _nice_integer_top(ymax * 1.15)
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
    if len(interior_ticks) > 5:
        step = int(np.ceil(len(interior_ticks) / 5))
        interior_ticks = interior_ticks[::step][:5]
    ticks = [bottom] + interior_ticks + [top]
    ax.set_yticks(ticks)


def ensure_y_tick(ax, tick_value):
    bottom, top = ax.get_ylim()
    if not (bottom < tick_value < top):
        return
    ticks = list(ax.get_yticks())
    if any(np.isclose(tick, tick_value) for tick in ticks):
        return
    ticks.append(tick_value)
    ax.set_yticks(sorted(ticks))


def style_axes(ax):
    ax.xaxis.label.set_color("black")
    ax.yaxis.label.set_color("black")
    ax.tick_params(axis="both", which="both", colors="black")
    for spine in ax.spines.values():
        spine.set_color("black")


def _pad_legend_first_column(handles, labels, ncol, first_col_items=None):
    n_items = len(labels)
    if ncol <= 1 or n_items <= 1 or first_col_items is None or first_col_items <= 0:
        return handles, labels

    first_len = min(first_col_items, n_items)
    if ncol == 2:
        other_lengths = [n_items - first_len]
    else:
        remaining = n_items - first_len
        remaining_cols = ncol - 1
        base = remaining // remaining_cols
        extra = remaining % remaining_cols
        other_lengths = [
            base + (1 if i < extra else 0)
            for i in range(remaining_cols)
        ]

    col_lengths = [first_len] + other_lengths
    max_rows = max(col_lengths) if col_lengths else first_len
    blanks = max_rows - first_len
    if blanks < 0:
        blanks = 0

    blank_handle = Line2D([], [], linestyle="none", marker=None, alpha=0.0)
    new_handles = list(handles[:first_len]) + [blank_handle] * blanks
    new_labels = list(labels[:first_len]) + [" "] * blanks

    start = first_len
    for length in other_lengths:
        new_handles.extend(handles[start:start + length])
        new_labels.extend(labels[start:start + length])
        start += length

    return new_handles, new_labels


def place_legend(ax, max_rows, ncol_override=None, first_col_items=None):
    handles, labels = ax.get_legend_handles_labels()
    n_items = len(labels)
    if ncol_override is not None and ncol_override > 0:
        ncol = ncol_override
    else:
        ncol = max(1, int(np.ceil(n_items / max_rows))) if max_rows > 0 else 1
    handles, labels = _pad_legend_first_column(handles, labels, ncol, first_col_items)
    ax.legend(
        handles,
        labels,
        fontsize=25,
        loc="upper left",
        ncol=ncol,
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


def draw_one_group(series_list, x_tick_labels, output_prefix, legend_max_rows,
                   legend_ncol=None, legend_first_col_items=None):
    series_list = sorted(series_list, key=_lb_sort_key)
    x_tick_positions = np.arange(len(x_tick_labels))
    visible_xticks, visible_xtick_labels = get_visible_xticks(x_tick_positions, x_tick_labels)

    gamma = 0.001

    def get_label(series):
        lb = _strip_w(series.get('load_balancing_mode', 'N/A'))
        rec = _strip_w(series.get('recovery_mechanism', 'N/A'))
        if str(lb).upper() == "DRILLGROUP":
            lb = "DRILL"
        rec_lower = str(rec).lower()
        if rec_lower == "idealtrimming+slowstart":
            return f"{lb}(Trim + Slow Start)"
        if rec_lower == "rto+gbn+slowstart":
            return f"{lb}(+Slow Start)"
        if "idealtrimming" in rec_lower:
            return f"{lb}(Trim)"
        return str(lb)

    # -------- AVG --------
    p_avg = plot.LinePointPlot()
    p_avg.fig.set_size_inches(9.6, 6.0)
    avg_values = []
    for s in series_list:
        y = s["avg_fct_slowdown"]
        if len(y) != len(x_tick_positions):
            print(f"⚠️ Warning: avg point count mismatch for {get_label(s)}; skipping.")
            continue
        avg_values.extend(y)

        p_avg.plot(
            x_tick_positions,
            y,
            label=get_label(s),
            markevery=1
        )

    p_avg.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
    p_avg.ax.set_ylabel("Average FCT Slowdown", fontsize=35)
    p_avg.ax.set_yscale(
        "function",
        functions=(lambda x: np.power(x, gamma),
                   lambda y: np.power(y, 1 / gamma))
    )
    apply_y_axis_bounds(p_avg.ax, avg_values)
    p_avg.ax.set_xticks(visible_xticks)
    p_avg.ax.set_xticklabels(
        visible_xtick_labels, rotation=45, ha='center', fontsize=26,
        fontweight='semibold', rotation_mode='anchor'
    )
    p_avg.ax.set_xlim(x_tick_positions[0] - 0.5, x_tick_positions[-1] + 0.5)
    p_avg.ax.tick_params(axis='x', which='major', direction='out', length=8, pad=10, colors="black")
    p_avg.ax.tick_params(axis='x', which='minor', direction='out', colors="black")
    p_avg.ax.tick_params(axis='y', which='major', labelsize=30, colors="black")
    p_avg.ax.tick_params(axis='y', which='minor', colors="black")
    style_axes(p_avg.ax)
    place_legend(p_avg.ax, legend_max_rows, legend_ncol, legend_first_col_items)

    avg_path = os.path.abspath(f"{output_prefix}_avg.pdf")
    plt.savefig(avg_path, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {avg_path}")

    # -------- P99 --------
    p_p99 = plot.LinePointPlot()
    p_p99.fig.set_size_inches(9.6, 6.0)
    p99_values = []
    for s in series_list:
        y = s["p99_fct_slowdown"]
        if len(y) != len(x_tick_positions):
            print(f"⚠️ Warning: p99 point count mismatch for {get_label(s)}; skipping.")
            continue
        p99_values.extend(y)

        p_p99.plot(
            x_tick_positions,
            y,
            label=get_label(s),
            markevery=1
        )

    p_p99.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
    p_p99.ax.set_ylabel("P99 FCT Slowdown", fontsize=35)
    p_p99.ax.set_yscale(
        "function",
        functions=(lambda x: np.power(x, gamma),
                   lambda y: np.power(y, 1 / gamma))
    )
    apply_y_axis_bounds(p_p99.ax, p99_values)
    ensure_y_tick(p_p99.ax, 25)
    ensure_y_tick(p_p99.ax, 50)
    ensure_y_tick(p_p99.ax, 100)
    p_p99.ax.set_xticks(visible_xticks)
    p_p99.ax.set_xticklabels(
        visible_xtick_labels, rotation=45, ha='center', fontsize=26,
        fontweight='semibold', rotation_mode='anchor'
    )
    p_p99.ax.set_xlim(x_tick_positions[0] - 0.5, x_tick_positions[-1] + 0.5)
    p_p99.ax.tick_params(axis='x', which='major', direction='out', length=8, pad=10, colors="black")
    p_p99.ax.tick_params(axis='x', which='minor', direction='out', colors="black")
    p_p99.ax.tick_params(axis='y', which='major', labelsize=30, colors="black")
    p_p99.ax.tick_params(axis='y', which='minor', colors="black")
    style_axes(p_p99.ax)
    place_legend(p_p99.ax, legend_max_rows, legend_ncol, legend_first_col_items)

    p99_path = os.path.abspath(f"{output_prefix}_p99.pdf")
    plt.savefig(p99_path, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {p99_path}")


FLOWLET_LBS = {"LETFLOW", "CONGA"}
# FLOWLET_LBS = {"LETFLOW"}


def draw_fct_plot(json_path, output_dir, exclude_lb=None,
                  no_trimming=False, no_rto_gbn_slowstart=False,
                  no_flowlet=False, legend_max_rows=99, legend_ncol=None,
                  legend_first_col_items=None):
    with open(json_path, 'r') as f:
        data = json.load(f)

    series_all = data.get("data_series", [])
    if exclude_lb:
        excluded = {lb.upper() for lb in exclude_lb}
        before = len(series_all)
        series_all = [s for s in series_all
                      if str(s.get("load_balancing_mode", "")).upper() not in excluded]
        if before != len(series_all):
            print(f"  (filtered out {before - len(series_all)} series with LB in {sorted(excluded)})")
    if no_trimming:
        before = len(series_all)
        series_all = [s for s in series_all
                      if "IdealTrimming" not in str(s.get("recovery_mechanism", ""))]
        if before != len(series_all):
            print(f"  (filtered out {before - len(series_all)} trimming series)")
    if no_rto_gbn_slowstart:
        before = len(series_all)
        series_all = [s for s in series_all
                      if str(s.get("recovery_mechanism", "")) != "RTO+GBN+slowstart"]
        if before != len(series_all):
            print(f"  (filtered out {before - len(series_all)} RTO+GBN+slowstart series)")
    if no_flowlet:
        before = len(series_all)
        series_all = [s for s in series_all
                      if str(s.get("load_balancing_mode", "")).upper() not in FLOWLET_LBS]
        if before != len(series_all):
            print(f"  (filtered out {before - len(series_all)} flowlet-based series)")
    if not series_all:
        print(f"⚠️ {json_path} has no data_series")
        return

    x_tick_labels = series_all[0]["flow_size_buckets_bytes"]
    base_name = os.path.splitext(os.path.basename(json_path))[0]

    # ===============================
    # 🔥 按 (rto_high, rto_low) 分组
    # ===============================
    groups = defaultdict(list)
    for s in series_all:
        rto_h = s.get("rto_high", "None")
        rto_l = s.get("rto_low", "None")
        key = (rto_h, rto_l)
        groups[key].append(s)

    print(f"📊 {base_name}: found {len(groups)} RTO groups")

    for (rto_h, rto_l), series_list in groups.items():
        prefix = os.path.join(
            output_dir,
            f"{base_name}_rtoH{rto_h}_L{rto_l}"
        )
        print(f"  ▶ Plotting RTO H={rto_h} L={rto_l} ({len(series_list)} lines)")
        draw_one_group(
            series_list, x_tick_labels, prefix, legend_max_rows,
            legend_ncol, legend_first_col_items
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path")
    parser.add_argument("--exclude-lb", nargs="*", default=["WAR"],
                        help="LB modes to drop (default: WAR). Pass empty to keep all.")
    parser.add_argument("--no-drill", action="store_true",
                        help="Exclude DRILL / DrillGroup series.")
    parser.add_argument("--no-rps", action="store_true",
                        help="Exclude RPS series.")
    parser.add_argument("--no-ecmp", action="store_true",
                        help="Exclude ECMP series.")
    parser.add_argument("--no-conweave", action="store_true",
                        help="Exclude ConWeave series.")
    parser.add_argument("--no-trimming", action="store_true",
                        help="Exclude any IdealTrimming-based recovery series.")
    parser.add_argument("--no-rto-gbn-slowstart", action="store_true",
                        help="Exclude 'RTO+GBN+slowstart' recovery series.")
    parser.add_argument("--no-flowlet", action="store_true",
                        help="Exclude flowlet-based LBs (LetFlow, CONGA).")
    parser.add_argument("--legend-max-rows", type=int, default=99,
                        help="Maximum legend entries per column before adding another column.")
    parser.add_argument("--legend-ncol", type=int, default=None,
                        help="Force legend into this many vertical columns.")
    parser.add_argument("--legend-first-col-items", type=int, default=None,
                        help="When using multi-column legend, force this many items in the first column.")
    args = parser.parse_args()

    exclude_lb = list(args.exclude_lb)
    if args.no_drill:
        exclude_lb.extend(["DRILL", "DRILLGROUP"])
    if args.no_rps:
        exclude_lb.append("RPS")
    if args.no_ecmp:
        exclude_lb.append("ECMP")
    if args.no_conweave:
        exclude_lb.append("CONWEAVE")

    path = os.path.abspath(os.path.expanduser(args.input_path))

    if os.path.isfile(path):
        draw_fct_plot(path, os.path.dirname(path),
                      exclude_lb=exclude_lb,
                      no_trimming=args.no_trimming,
                      no_rto_gbn_slowstart=args.no_rto_gbn_slowstart,
                      no_flowlet=args.no_flowlet,
                      legend_max_rows=args.legend_max_rows,
                      legend_ncol=args.legend_ncol,
                      legend_first_col_items=args.legend_first_col_items)
    else:
        for f in glob.glob(os.path.join(path, "*.json")):
            draw_fct_plot(f, path,
                          exclude_lb=exclude_lb,
                          no_trimming=args.no_trimming,
                          no_rto_gbn_slowstart=args.no_rto_gbn_slowstart,
                          no_flowlet=args.no_flowlet,
                          legend_max_rows=args.legend_max_rows,
                          legend_ncol=args.legend_ncol,
                          legend_first_col_items=args.legend_first_col_items)


if __name__ == "__main__":
    main()
