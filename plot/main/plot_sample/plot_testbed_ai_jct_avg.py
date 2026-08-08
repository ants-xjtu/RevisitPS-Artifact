#!/usr/bin/python3
"""
Testbed AI-workload Average CCT Plotting Script

Reads the CCT JSON files under
`simulation/parser/json-data-testbed-ai-jct/` and produces
grouped bar charts of the MEAN CCT (us) across the np=8 workloads
(AlltoAll, AlltoAllV, RingAllReduce). One PDF per loss_mode.

Expected JSON schema per file:
  {
    "datasets": [
      {
        "label": "<original label>",
        "jct_us": [<floats>],
        "lb":   "RPS" | "ECMP" | "BigSwitch",
        "cc":   "None" | "DCQCN",
        "loss_recovery": "RTO + GBN" | "NAK + GBN",
        "loss_mode": "Lossless" | "Lossy",
        "np":   8 | 16
      },
      ...
    ]
  }
"""

import argparse
import glob
import json
import math
import os

import matplotlib.pyplot as plt
import numpy as np

import lib.py.plot.plot as plot


# ── Display/order configuration ───────────────────────────────────────────────
FONT_FAMILY = "DejaVu Sans"
LB_ORDER = ["ECMP", "RPS", "BigSwitch"]
CC_ORDER = ["DCQCN", "None"]

# np=8 workloads we want on the same figure and their display names.
# Order here defines the x-axis ordering.
WORKLOADS = [
    ("ringallreduce", "AllR"),
    ("alltoall", "A2A"),
    ("alltoallv_np8", "A2Av"),
]

# Optimal CCT for the --normalize option: transfer 150 MB over a 98 Gbps link.
#   150 MB  = 150 * 10^6 * 8 bits = 1.2e9 bits
#   98 Gbps = 98 * 10^9 bits/s
#   => 12244.9 us
OPTIMAL_SIZE_BYTES = 150 * 10**6
OPTIMAL_BW_BPS = 98 * 10**9
OPTIMAL_CCT_US = OPTIMAL_SIZE_BYTES * 8 / OPTIMAL_BW_BPS * 1e6


def _match_workload(filename):
    """Return the workload key ('alltoall', 'alltoallv_np8', 'ringallreduce')
    if this filename matches one of the np=8 workloads, else None."""
    name = os.path.basename(filename).lower()
    if name.startswith("alltoallv_np8_"):
        return "alltoallv_np8"
    if name.startswith("alltoallv_np16_"):
        return None
    if name.startswith("alltoall_"):
        return "alltoall"
    if name.startswith("ringallreduce_"):
        return "ringallreduce"
    return None


def _match_loss_mode(filename):
    name = os.path.basename(filename).lower()
    if "_lossless_" in name:
        return "Lossless"
    if "_lossy_" in name:
        return "Lossy"
    return None


def _series_label(lb, loss_recovery, cc, show_cc):
    if cc == "None":
        return f"{lb} w/o CC"
    return lb


def _nice_top(x):
    """Round x up to a visually 'nice' number (1, 2, 2.5, 3, 5, 10 x 10^n)."""
    if x <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(x))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= x:
            return m * exp
    return 10 * exp


def _series_sort_key(key):
    lb, loss_recovery, cc = key
    lb_idx = LB_ORDER.index(lb) if lb in LB_ORDER else len(LB_ORDER)
    cc_idx = CC_ORDER.index(cc) if cc in CC_ORDER else len(CC_ORDER)
    return (cc_idx, lb_idx)


def _set_black_text_and_frame(ax):
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.tick_params(axis="both", which="both", colors="black")
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("black")
        label.set_fontfamily(FONT_FAMILY)


def _filter_jct_values(jct_values, cc):
    if cc == "None":
        return [v for v in jct_values if v <= 20000]
    return list(jct_values)


def _collect(json_files, loss_mode, dcqcn_only):
    """Return {(lb, loss_recovery, cc): {workload_key: mean_cct_us}}."""
    result = {}
    for jf in json_files:
        wk = _match_workload(jf)
        if wk is None:
            continue
        if _match_loss_mode(jf) != loss_mode:
            continue
        with open(jf, "r") as f:
            data = json.load(f)
        for ds in data.get("datasets", []):
            if not ds.get("jct_us"):
                continue
            cc = ds.get("cc", "?")
            if dcqcn_only and cc != "DCQCN":
                continue
            key = (ds.get("lb", "?"), ds.get("loss_recovery", "?"), cc)
            jct_values = _filter_jct_values(ds["jct_us"], cc)
            if not jct_values:
                continue
            mean = float(np.mean(jct_values))
            # If duplicate entries exist for the same config+workload, keep the smaller.
            prev = result.setdefault(key, {}).get(wk)
            result[key][wk] = mean if prev is None else min(prev, mean)
    return result


def _collect_box(json_files, loss_mode, dcqcn_only):
    """Return {(lb, loss_recovery, cc): {workload_key: [jct_us...]}}."""
    result = {}
    for jf in json_files:
        wk = _match_workload(jf)
        if wk is None:
            continue
        if _match_loss_mode(jf) != loss_mode:
            continue
        with open(jf, "r") as f:
            data = json.load(f)
        for ds in data.get("datasets", []):
            if not ds.get("jct_us"):
                continue
            cc = ds.get("cc", "?")
            if dcqcn_only and cc != "DCQCN":
                continue
            values = _filter_jct_values(ds["jct_us"], cc)
            if not values:
                continue
            key = (ds.get("lb", "?"), ds.get("loss_recovery", "?"), cc)
            result.setdefault(key, {}).setdefault(wk, []).extend(float(v) for v in values)
    return result


def _filter_series_by_lb(series_data, no_ecmp, no_bigswitch):
    filtered = {}
    for key, value in series_data.items():
        lb, _, _ = key
        if no_ecmp and lb == "ECMP":
            continue
        if no_bigswitch and lb == "BigSwitch":
            continue
        filtered[key] = value
    return filtered


def _legend_ncol(n_items, max_rows):
    if max_rows is None or max_rows <= 0:
        return 1
    return max(1, int(math.ceil(n_items / max_rows)))


def draw_figure(series_data, loss_mode, output_dir, dcqcn_only, normalize,
                raw_ytop, raw_ystep, legend_max_rows, normalize_ymin,
                normalize_ytop):
    if not series_data:
        print(f"  [WARN] No data for {loss_mode}"
              + (" (DCQCN only)" if dcqcn_only else ""))
        return

    show_cc = not dcqcn_only
    series_keys = sorted(series_data.keys(), key=_series_sort_key)
    workload_keys = [wk for wk, _ in WORKLOADS]
    workload_names = [name for _, name in WORKLOADS]

    p = plot.BarPlot()
    # Widen bar footprint so multiple series fit comfortably.
    p.total_bar_width = 0.85

    for key in series_keys:
        lb, rec, cc = key
        yvals = [series_data[key].get(wk, 0.0) for wk in workload_keys]
        if normalize:
            yvals = [v / OPTIMAL_CCT_US for v in yvals]
        label = _series_label(lb, rec, cc, show_cc)
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=workload_names)

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=35)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=35)
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelsize=30)
    ax.tick_params(axis="y", labelsize=30)
    ax.grid(False, axis="x")
    ax.grid(True, axis="y")

    legend = ax.legend(fontsize=25,
                       prop={"family": FONT_FAMILY, "size": 25},
                       loc="best",
                       ncol=_legend_ncol(len(series_keys), legend_max_rows),
                       frameon=True,
                       edgecolor="dimgray", facecolor="white",
                       framealpha=1.0, borderaxespad=0.5,
                       handlelength=1.4, handletextpad=0.35)
    legend.set_zorder(200)
    _set_black_text_and_frame(ax)

    # Y-axis range: user override if provided; otherwise raw has fixed ticks and
    # normalized uses a nice round top.
    all_vals = [v for d in series_data.values() for v in d.values() if v]
    if normalize:
        all_vals = [v / OPTIMAL_CCT_US for v in all_vals]
    if all_vals:
        if raw_ytop is not None:
            top = raw_ytop
        elif normalize:
            top = _nice_top(max(all_vals) * 1.1)
        else:
            top = 45000
        ax.set_ylim(bottom=0, top=top)

        if raw_ystep is not None:
            step = raw_ystep
            ax.set_yticks(np.arange(0, top + step * 0.5, step))
        elif normalize:
            ax.set_yticks(np.linspace(0, top, 6))
        else:
            ax.set_yticks(np.arange(0, top + 2500, 5000))
    if normalize and (normalize_ymin is not None or normalize_ytop is not None):
        cur_bottom, cur_top = ax.get_ylim()
        ax.set_ylim(
            bottom=normalize_ymin if normalize_ymin is not None else cur_bottom,
            top=normalize_ytop if normalize_ytop is not None else cur_top,
        )

    parts = ["cct"]
    parts.append("norm" if normalize else "avg")
    parts.append("np8")
    if dcqcn_only:
        parts.append("dcqcn")
    parts.append(loss_mode.lower())
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    plt.savefig(out_path, bbox_inches="tight", pad_inches=0.12)
    plt.close()
    print(f"  Saved: {out_path}")


def draw_box_figure(series_data, loss_mode, output_dir, dcqcn_only, normalize,
                    raw_ytop, raw_ystep, legend_max_rows, normalize_ymin,
                    normalize_ytop):
    if not series_data:
        print(f"  [WARN] No data for {loss_mode}"
              + (" (DCQCN only)" if dcqcn_only else ""))
        return

    series_keys = sorted(series_data.keys(), key=_series_sort_key)
    workload_keys = [wk for wk, _ in WORKLOADS]
    workload_names = [name for _, name in WORKLOADS]
    group_centers = np.arange(len(workload_keys))
    total_width = 0.85
    box_width = total_width / max(len(series_keys), 1)
    fig, ax = plt.subplots()
    fig.set_size_inches(9.6, 6)
    all_vals = []

    for idx, key in enumerate(series_keys):
        lb, rec, cc = key
        label = _series_label(lb, rec, cc, not dcqcn_only)
        offset = -total_width / 2 + (idx + 0.5) * box_width
        positions = group_centers + offset
        data = []
        valid_positions = []
        for pos, wk in zip(positions, workload_keys):
            vals = series_data.get(key, {}).get(wk, [])
            if not vals:
                continue
            vals = [v / OPTIMAL_CCT_US for v in vals] if normalize else vals
            data.append(vals)
            valid_positions.append(pos)
            all_vals.extend(vals)
        if not data:
            continue
        color = plot.colors[idx % len(plot.colors)]
        bp = ax.boxplot(
            data,
            positions=valid_positions,
            widths=box_width * 0.72,
            patch_artist=True,
            manage_ticks=False,
            showfliers=False,
        )
        for box in bp["boxes"]:
            box.set(facecolor=color, edgecolor="black", alpha=0.78)
        for median in bp["medians"]:
            median.set(color="black", linewidth=2)
        for whisker in bp["whiskers"]:
            whisker.set(color="black", linewidth=1.5)
        for cap in bp["caps"]:
            cap.set(color="black", linewidth=1.5)
        ax.plot([], [], color=color, linewidth=10, label=label)

    ax.set_xticks(group_centers)
    ax.set_xticklabels(workload_names)
    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=35)
    else:
        ax.set_ylabel("CCT (us)", fontsize=35)
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelsize=30)
    ax.tick_params(axis="y", labelsize=30)
    ax.grid(False, axis="x")
    ax.grid(True, axis="y")

    legend = ax.legend(fontsize=25,
                       prop={"family": FONT_FAMILY, "size": 25},
                       loc="best",
                       ncol=_legend_ncol(len(series_keys), legend_max_rows),
                       frameon=True,
                       edgecolor="dimgray", facecolor="white",
                       framealpha=1.0, borderaxespad=0.5,
                       handlelength=1.4, handletextpad=0.35)
    legend.set_zorder(200)
    _set_black_text_and_frame(ax)

    if all_vals:
        if raw_ytop is not None:
            top = raw_ytop
        elif normalize:
            top = _nice_top(max(all_vals) * 1.1)
        else:
            top = 45000
        ax.set_ylim(bottom=0, top=top)
        if raw_ystep is not None:
            step = raw_ystep
            ax.set_yticks(np.arange(0, top + step * 0.5, step))
        elif normalize:
            ax.set_yticks(np.linspace(0, top, 6))
        else:
            ax.set_yticks(np.arange(0, top + 2500, 5000))
    if normalize and (normalize_ymin is not None or normalize_ytop is not None):
        cur_bottom, cur_top = ax.get_ylim()
        ax.set_ylim(
            bottom=normalize_ymin if normalize_ymin is not None else cur_bottom,
            top=normalize_ytop if normalize_ytop is not None else cur_top,
        )

    parts = ["cct", "box"]
    parts.append("norm" if normalize else "raw")
    parts.append("np8")
    if dcqcn_only:
        parts.append("dcqcn")
    parts.append(loss_mode.lower())
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    plt.savefig(out_path, bbox_inches="tight", pad_inches=0.12)
    plt.close()
    print(f"  Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot average CCT bar charts from testbed AI-workload JSON files.")
    parser.add_argument(
        "input_path", type=str,
        help="Directory containing *_jct_boxplot.json (or a single JSON file).")
    parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="Output directory for PDFs (defaults to the input directory).")
    parser.add_argument(
        "--dcqcn-only", action="store_true",
        help="Only plot bars whose CC is DCQCN.")
    parser.add_argument(
        "--normalize", action="store_true",
        help=f"Plot Normalized CCT (mean / optimal). Optimal = 150MB / 98Gbps "
             f"= {OPTIMAL_CCT_US:.1f} us.")
    parser.add_argument(
        "--raw-ytop", type=float, default=None,
        help="Top y-axis value override. Applies to raw and normalized plots.")
    parser.add_argument(
        "--raw-ystep", type=float, default=None,
        help="Y-axis tick step override. Applies to raw and normalized plots.")
    parser.add_argument(
        "--plot-type", choices=["bar", "box"], default="bar",
        help="Choose grouped bar plot from means or grouped boxplot from raw samples.")
    parser.add_argument(
        "--legend-max-rows", type=int, default=99,
        help="Maximum legend entries per column before adding another column.")
    parser.add_argument(
        "--normalize-ymin", type=float, default=None,
        help="Bottom y-axis value override for normalized plots.")
    parser.add_argument(
        "--normalize-ytop", type=float, default=None,
        help="Top y-axis value override for normalized plots.")
    parser.add_argument(
        "--no-ecmp", action="store_true",
        help="Exclude ECMP series.")
    parser.add_argument(
        "--no-bigswitch", action="store_true",
        help="Exclude BigSwitch series.")
    args = parser.parse_args()

    input_path = args.input_path
    if os.path.isfile(input_path):
        json_files = [input_path]
        output_dir = args.output_dir or os.path.dirname(input_path) or "."
    elif os.path.isdir(input_path):
        json_files = sorted(glob.glob(os.path.join(input_path, "*_jct_boxplot.json")))
        output_dir = args.output_dir or input_path
        if not json_files:
            print(f"No *_jct_boxplot.json files found in: {input_path}")
            return
    else:
        print(f"Error: not a valid file or directory: {input_path}")
        return

    os.makedirs(output_dir, exist_ok=True)
    print(f"Found {len(json_files)} file(s). Output dir: {output_dir}"
          + (" [DCQCN only]" if args.dcqcn_only else ""))

    for loss_mode in ("Lossless", "Lossy"):
        print(f"--- {loss_mode} ---")
        if args.plot_type == "box":
            series = _collect_box(json_files, loss_mode, args.dcqcn_only)
            series = _filter_series_by_lb(series, args.no_ecmp, args.no_bigswitch)
            draw_box_figure(series, loss_mode, output_dir, args.dcqcn_only,
                            args.normalize, args.raw_ytop, args.raw_ystep,
                            args.legend_max_rows, args.normalize_ymin,
                            args.normalize_ytop)
        else:
            series = _collect(json_files, loss_mode, args.dcqcn_only)
            series = _filter_series_by_lb(series, args.no_ecmp, args.no_bigswitch)
            draw_figure(series, loss_mode, output_dir, args.dcqcn_only,
                        args.normalize, args.raw_ytop, args.raw_ystep,
                        args.legend_max_rows, args.normalize_ymin,
                        args.normalize_ytop)

    print("Done.")


if __name__ == "__main__":
    main()
