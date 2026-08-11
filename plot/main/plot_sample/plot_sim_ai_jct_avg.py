#!/usr/bin/python3
"""
Simulation AI-workload Average CCT Plotting Script

Reads JCT_VS_GROUPSIZE_*.json files (one file per workload / topology /
flow_control combination) and produces ONE grouped bar chart per file,
with group_size on the x-axis and one bar series per (LB, recovery, CC)
configuration.

Expected JSON schema:
  {
    "metadata": {
      "topology": "<topo>",
      "load_type": "Alltoall" | "AlltoallV" | "RingAllreduce",
      "flow_control": "Lossless" | "Lossy",
      "message_size_name": "<e.g. 21MB>",
      ...
    },
    "data_series": [
      {
        "load_balancing_mode": "AR" | "ECMP" | ...,
        "recovery_mechanism": "NAK+GBN" | "RTO+GBN" | ...,
        "congestion_control": "DCQCN" | "NONE",
        "timeout_mode": "0" | ...,
        "points": [
          {"group_size": <int>, "jct_us": <float>, "ideal_jct_us": <float>, ...},
          ...
        ]
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

FONT_FAMILY = "DejaVu Sans"


# ── Display/order configuration ───────────────────────────────────────────────
LB_ORDER = ["ECMP", "LetFlow", "CONGA", "ConWeave", "DRILL", "RPS", "AR"]
CC_ORDER = ["DCQCN", "NONE"]

# timeout_mode is the source of truth for the "+1/N" suffix: any recovery
# paired with timeout_mode=N (N != "0") renders as "<recovery>+1/N". An
# existing "+1/M" already baked into recovery_mechanism is stripped first
# so timeout_mode wins (avoids e.g. "RTO+GBN+1/2+1/2").
import re as _re
_TIMEOUT_SUFFIX_RE = _re.compile(r"\+1/\d+$")


# Combined-mode x-axis categories: (load_type, group_size, display_label).
COMBINED_CATEGORIES = [
    ("AlltoallV", 32, "A2Av-32"),
    ("AlltoallV", 64, "A2Av-64"),
    ("AlltoallV", 128, "A2Av-128"),
]

# Combined-group templates.
# - "default": current active categories.
# - "1", "2": placeholders for custom category groups (keep empty for now).
COMBINED_GROUP_CATEGORIES = {
    "default": COMBINED_CATEGORIES,
    "lossless-low-incast": [
        ("Alltoall", 8, "A2A"),
        ("RingAllreduce", 8, "AllR"),
        ("AlltoallV", 8, "A2Av-8"),
        ("AlltoallV", 16, "A2Av-16"),
    ],
    "lossless-high-incast": COMBINED_CATEGORIES,
    "1": [("ECMP",     "NAK+GBN",            "DCQCN"),
    ("ConWeave", "NAK+GBN",            "DCQCN"),
    ("DRILL",    "RTO+GBN",           "DCQCN"),
    ("RPS",      "RTO+GBN",           "DCQCN"),
    ("AR",       "RTO+GBN",           "DCQCN"),
    ("DRILL",    "RTO+GBN",           "NONE"),
    ("RPS",      "RTO+GBN",           "NONE"),
    ("AR",       "RTO+GBN",           "NONE"),],
    "2": [    ("ECMP",     "NAK+SR",            "DCQCN"),
    ("ConWeave",    "NAK+SR",            "DCQCN"),
    ("DRILL",    "RTO+GBN+1/2",       "DCQCN"),
    ("RPS",      "RTO+GBN+1/2",       "DCQCN"),
    ("AR",       "RTO+GBN+1/2",       "DCQCN"),],
    "3": [    ("ECMP",     "NAK+GBN",            "DCQCN"),
    ("ConWeave",    "NAK+GBN",            "DCQCN"),
    ("DRILL",    "RTO+GBN+1/2",       "DCQCN"),
    ("RPS",      "RTO+GBN+1/2",       "DCQCN"),
    ("AR",       "RTO+GBN+1/2",       "DCQCN"),],
    "4": [    ("ECMP",     "NAK+SR",            "DCQCN"),
    ("ConWeave",    "NAK+SR",            "DCQCN"),
    # ("DRILL",    "RTO+GBN+1/2",       "DCQCN"),
    # ("RPS",      "RTO+GBN+1/2",       "DCQCN"),
    ("AR",       "RTO+GBN+1/2",       "DCQCN"),
    ("AR",       "IdealTrimming",       "DCQCN"),
    ("AR",       "RTO+GBN+1/8",       "DCQCN"),
    ("AR",       "RTO+GBN+1/32",       "DCQCN"),
    ("AR",       "RTO+GBN+1/128",       "DCQCN"),],
}


# (lb, recovery, cc) combos to draw, in the order they should appear on the
# plot (legend + bars). Recovery here is the effective name after merging in
# timeout_mode (e.g. timeout_mode=4 -> "...+1/4"). Comment out any row to
# drop that series. Empty list => no filter, fall back to (cc, lb, recovery).
# INCLUDE_COMBOS = [
#     ("ECMP", "NAK+SR", "DCQCN"),
#     ("CONGA", "NAK+SR", "DCQCN"),
#     ("DRILL", "RTO+GBN+1/2", "DCQCN"),
#     ("RPS", "RTO+GBN+1/2", "DCQCN"),
#     ("AR", "IdealTrimming", "DCQCN"),
#     ("AR", "RTO+GBN+1/2", "DCQCN"),
# ]

INCLUDE_COMBOS = [

]


_COMBO_FILTER_ENABLED = True


def _canonical_recovery_for_match(recovery):
    """Normalize recoveries that should be treated as equivalent in filters."""
    if recovery in ("RTO+GBN", "RTO+GBN+1/2"):
        return "RTO+GBN"
    return recovery


def _canonical_combo_for_match(combo):
    lb, rec, cc = combo
    return (lb, _canonical_recovery_for_match(rec), cc)


def _canonical_combo_for_series(lb, rec, cc):
    """Normalize the internal series key so equivalent recoveries collapse."""
    return (lb, _canonical_recovery_for_match(rec), cc)


def _combo_included(lb, rec, cc):
    if not _COMBO_FILTER_ENABLED or not INCLUDE_COMBOS:
        return True
    wanted = _canonical_combo_for_match((lb, rec, cc))
    return any(_canonical_combo_for_match(combo) == wanted
               for combo in INCLUDE_COMBOS)


def _effective_recovery(recovery, timeout_mode):
    """Name a series as '<recovery>+1/<timeout_mode>' when timeout_mode is a
    non-zero integer string; otherwise just the bare recovery. Any '+1/N'
    pre-baked into recovery is stripped so timeout_mode is authoritative."""
    base = _TIMEOUT_SUFFIX_RE.sub("", recovery)
    tm = str(timeout_mode) if timeout_mode is not None else "0"
    if tm and tm != "0":
        return f"{base}+1/{tm}"
    return base


def _nice_top(x):
    """Round x up to a visually 'nice' number (1, 1.5, 2, 2.5, 3, 5, 10 x 10^n)."""
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


def _get_combined_group_settings(group_name):
    cats = COMBINED_GROUP_CATEGORIES.get(group_name)
    if cats is None:
        print(f"[WARN] Unknown combined-group '{group_name}', fallback to 'default'.")
        return COMBINED_GROUP_CATEGORIES["default"], "default", None
    if not cats:
        print(f"[WARN] combined-group '{group_name}' is empty, fallback to 'default'.")
        return COMBINED_GROUP_CATEGORIES["default"], "default", None

    first = cats[0]
    # Compatibility mode: if group entries look like (lb, recovery, cc),
    # treat them as combo filter and keep default combined categories.
    if (
        isinstance(first, (tuple, list))
        and len(first) == 3
        and not isinstance(first[1], int)
    ):
        print(f"[WARN] combined-group '{group_name}' contains combo tuples; "
              "use as INCLUDE_COMBOS override with default categories.")
        return COMBINED_GROUP_CATEGORIES["default"], group_name, cats
    return cats, group_name, None


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


_RECOVERY_DISPLAY = {
    "IdealTrimming": "Packet-trimming",
}


def _display_recovery(recovery):
    return _RECOVERY_DISPLAY.get(recovery, recovery)


def _is_trimming(recovery):
    return recovery.startswith("IdealTrimming")


def _ar_recovery_suffix(recovery):
    if recovery in ("RTO+GBN", "RTO+GBN+1/2"):
        return ""
    match = _re.search(r"\+1/(\d+)$", recovery)
    if match:
        return f"1/{match.group(1)}"
    return _display_recovery(recovery)


def _series_label(lb, recovery, cc, show_cc, show_recovery=False):
    label = f"{lb}(Trim)" if _is_trimming(str(recovery)) else lb
    if show_recovery and not _is_trimming(str(recovery)):
        if lb == "AR":
            suffix = _ar_recovery_suffix(str(recovery))
            if suffix:
                label += f" ({suffix})"
        else:
            label += f" ({_display_recovery(recovery)})"
    if str(cc).upper() == "NONE":
        label += " w/o CC"
    return label


def _series_sort_key(key):
    if _COMBO_FILTER_ENABLED and INCLUDE_COMBOS:
        norm_key = _canonical_combo_for_match(key)
        try:
            return next(
                (idx,)
                for idx, combo in enumerate(INCLUDE_COMBOS)
                if _canonical_combo_for_match(combo) == norm_key
            )
        except StopIteration:
            return (len(INCLUDE_COMBOS),)
    lb, recovery, cc = key
    lb_idx = LB_ORDER.index(lb) if lb in LB_ORDER else len(LB_ORDER)
    cc_idx = CC_ORDER.index(cc) if cc in CC_ORDER else len(CC_ORDER)
    return (cc_idx, lb_idx, recovery)


def _series_sort_key_for_order(key, ordered_combos):
    norm_key = _canonical_combo_for_match(key)
    try:
        return next(
            (idx,)
            for idx, combo in enumerate(ordered_combos)
            if _canonical_combo_for_match(combo) == norm_key
        )
    except StopIteration:
        return (len(ordered_combos),) + _series_sort_key(key)


def _collect_from_file(data, dcqcn_only, no_trimming):
    """Return (sorted group_sizes, {(lb, recovery, cc): {group_size: (mean, ideal)}})."""
    series_map = {}
    group_sizes = set()
    for series in data.get("data_series", []):
        cc = series.get("congestion_control", "?")
        if dcqcn_only and cc != "DCQCN":
            continue
        lb = series.get("load_balancing_mode", "?")
        rec = _effective_recovery(series.get("recovery_mechanism", "?"),
                                  series.get("timeout_mode"))
        if no_trimming and _is_trimming(rec):
            continue
        if not _combo_included(lb, rec, cc):
            continue
        key = _canonical_combo_for_series(lb, rec, cc)
        for pt in series.get("points", []):
            gs = pt.get("group_size")
            mean = pt.get("jct_us")
            ideal = pt.get("ideal_jct_us")
            if gs is None or mean is None:
                continue
            group_sizes.add(gs)
            entry = series_map.setdefault(key, {})
            val = (float(mean), float(ideal) if ideal else None)
            prev = entry.get(gs)
            if prev is None or prev[0] > val[0]:
                entry[gs] = val
    return sorted(group_sizes), series_map


def _group_by_topo_fc(json_files):
    """Group JSON files by (topology, flow_control) and keep per load_type."""
    groups = {}
    for jf in json_files:
        with open(jf, "r") as f:
            data = json.load(f)
        meta = data.get("metadata", {})
        topo = meta.get("topology", "unknown")
        fc = meta.get("flow_control", "unknown")
        load_type = meta.get("load_type", "unknown")
        groups.setdefault((topo, fc), {})[load_type] = data
    return groups


def _collect_combined_series(workload_data, combined_categories, dcqcn_only,
                             no_trimming, combo_override):
    series_map = {}
    for i, (load_type, gs, _label) in enumerate(combined_categories):
        data = workload_data.get(load_type)
        if not data:
            continue
        for series in data.get("data_series", []):
            cc = series.get("congestion_control", "?")
            if dcqcn_only and cc != "DCQCN":
                continue
            lb = series.get("load_balancing_mode", "?")
            rec = _effective_recovery(
                series.get("recovery_mechanism", "?"),
                series.get("timeout_mode"),
            )
            if no_trimming and _is_trimming(rec):
                continue
            if combo_override is not None:
                wanted = _canonical_combo_for_match((lb, rec, cc))
                if not any(
                    _canonical_combo_for_match(combo) == wanted
                    for combo in combo_override
                ):
                    continue
            elif not _combo_included(lb, rec, cc):
                continue

            best = None
            for point in series.get("points", []):
                if point.get("group_size") != gs:
                    continue
                mean = point.get("jct_us")
                ideal = point.get("ideal_jct_us")
                if mean is None:
                    continue
                value = (float(mean), float(ideal) if ideal else None)
                if best is None or best[0] > value[0]:
                    best = value
            if best is None:
                continue

            key = _canonical_combo_for_series(lb, rec, cc)
            entry = series_map.setdefault(
                key, [None] * len(combined_categories)
            )
            if entry[i] is None or entry[i][0] > best[0]:
                entry[i] = best
    return series_map


def draw_combined(topo, fc, workload_data, output_dir, dcqcn_only, normalize,
                  raw_ytop, raw_ystep, no_trimming, combined_group):
    """Draw ONE bar chart per (topology, flow_control) combining AlltoAll,
    RingAllreduce, and AlltoAllV (np=8, np=16) on the x-axis."""
    combined_categories, resolved_group, combo_override = _get_combined_group_settings(combined_group)
    series_map = _collect_combined_series(
        workload_data,
        combined_categories,
        dcqcn_only,
        no_trimming,
        combo_override,
    )

    if not series_map:
        print(f"  [WARN] No drawable data for {topo} / {fc}")
        return

    show_cc = not dcqcn_only
    if combo_override is not None:
        series_keys = sorted(
            series_map.keys(),
            key=lambda key: _series_sort_key_for_order(key, combo_override),
        )
    else:
        series_keys = sorted(series_map.keys(), key=_series_sort_key)
    lb_counts = {}
    for lb, _rec, _cc in series_keys:
        lb_counts[lb] = lb_counts.get(lb, 0) + 1
    show_recovery = resolved_group == "4"
    category_names = [name for (_, _, name) in combined_categories]

    p = plot.BarPlot()
    p.total_bar_width = 0.85

    for key in series_keys:
        lb, rec, cc = key
        yvals = []
        for entry in series_map[key]:
            if entry is None:
                yvals.append(0.0)
                continue
            mean, ideal = entry
            if normalize:
                yvals.append(mean / ideal if ideal else 0.0)
            else:
                yvals.append(mean)
        label = _series_label(
            lb,
            rec,
            cc,
            show_cc,
            show_recovery=show_recovery and lb_counts.get(lb, 0) > 1,
        )
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=category_names, linewidth=3)

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=35)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=35)
    ax.set_xlabel("", fontsize=35)
    ax.tick_params(axis="x", labelsize=30)
    ax.tick_params(axis="y", labelsize=30)

    legend = ax.legend(fontsize=25,
                       prop={"family": FONT_FAMILY, "size": 25},
                       loc="best",
                       ncol=2,
                       frameon=True,
                       edgecolor="dimgray",
                       facecolor="white",
                       framealpha=1.0,
                       borderaxespad=0.2,
                       borderpad=0.2,
                       columnspacing=0.4,
                       handletextpad=0.2,
                       labelspacing=0.15,
                       handlelength=1.0)
    legend.set_zorder(200)
    _apply_plot_style(ax, legend)

    all_vals = []
    for entries in series_map.values():
        for entry in entries:
            if entry is None:
                continue
            mean, ideal = entry
            if normalize:
                if ideal:
                    all_vals.append(mean / ideal)
            else:
                all_vals.append(mean)
    if all_vals:
        if raw_ytop is not None:
            top = raw_ytop
        else:
            top = _nice_top(max(all_vals) * 1.1)
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

    parts = ["combined", topo, fc.lower(), "norm" if normalize else "avg"]
    if dcqcn_only:
        parts.append("dcqcn")
    if resolved_group != "default":
        parts.append(f"group{resolved_group}")
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  [combined | {fc} | {topo}] -> {out_path}")


def draw_one_file(json_path, output_dir, dcqcn_only, normalize,
                  raw_ytop, raw_ystep, no_trimming):
    with open(json_path, "r") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    topo = meta.get("topology", "unknown")
    load_type = meta.get("load_type", "unknown")
    loss_mode = meta.get("flow_control", "unknown")
    msg_size = meta.get("message_size_name", "")

    group_sizes, series_map = _collect_from_file(data, dcqcn_only, no_trimming)
    if not series_map or not group_sizes:
        print(f"  [WARN] No drawable data in {os.path.basename(json_path)}")
        return

    show_cc = not dcqcn_only
    series_keys = sorted(series_map.keys(), key=_series_sort_key)
    lb_counts = {}
    for lb, _rec, _cc in series_keys:
        lb_counts[lb] = lb_counts.get(lb, 0) + 1

    p = plot.BarPlot()
    p.total_bar_width = 0.85

    for key in series_keys:
        lb, rec, cc = key
        yvals = []
        for gs in group_sizes:
            entry = series_map[key].get(gs)
            if entry is None:
                yvals.append(0.0)
                continue
            mean, ideal = entry
            if normalize:
                yvals.append(mean / ideal if ideal else 0.0)
            else:
                yvals.append(mean)
        label = _series_label(lb, rec, cc, show_cc, show_recovery=False)
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=[str(gs) for gs in group_sizes])

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=35)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=35)
    ax.set_xlabel("Group Size", fontsize=35)
    ax.tick_params(axis="x", labelsize=30)
    ax.tick_params(axis="y", labelsize=30)

    legend = ax.legend(fontsize=25,
                       prop={"family": FONT_FAMILY, "size": 25},
                       loc="best",
                       ncol=2,
                       frameon=True,
                       edgecolor="dimgray",
                       facecolor="white",
                       framealpha=1.0,
                       borderaxespad=0.2,
                       borderpad=0.2,
                       columnspacing=0.4,
                       handletextpad=0.2,
                       labelspacing=0.15,
                       handlelength=1.0)
    legend.set_zorder(200)
    _apply_plot_style(ax, legend)

    # Y-axis ticks.
    all_vals = []
    for d in series_map.values():
        for mean, ideal in d.values():
            if normalize:
                if ideal:
                    all_vals.append(mean / ideal)
            else:
                all_vals.append(mean)
    if all_vals:
        # User-supplied limits override auto-pick, in both raw and normalized modes.
        if raw_ytop is not None:
            top = raw_ytop
        else:
            top = _nice_top(max(all_vals) * 1.1)
        if raw_ystep is not None:
            step = raw_ystep
        elif normalize:
            step = None  # fall back to linspace below
        else:
            step = _nice_step(top / 9)
        ax.set_ylim(bottom=0, top=top)
        if step is not None:
            ax.set_yticks(np.arange(0, top + step * 0.5, step))
        else:
            ax.set_yticks(np.linspace(0, top, 6))

    base = os.path.splitext(os.path.basename(json_path))[0]
    parts = [base, "norm" if normalize else "avg"]
    if dcqcn_only:
        parts.append("dcqcn")
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    print(f"  [{load_type} | {msg_size} | {loss_mode} | {topo}] -> {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot per-file CCT bar charts from simulation AI-workload JSON files.")
    parser.add_argument(
        "input_path", type=str,
        help="Directory containing JCT_VS_GROUPSIZE_*.json, or a single JSON file.")
    parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="Output directory for PDFs (defaults to the input directory).")
    parser.add_argument(
        "--dcqcn-only", action="store_true",
        help="Only plot bars whose CC is DCQCN.")
    parser.add_argument(
        "--normalize", action="store_true",
        help="Plot Normalized CCT (mean / ideal_jct_us from each point).")
    parser.add_argument(
        "--raw-ytop", type=float, default=None,
        help="Y-axis top for raw Average CCT mode (auto if omitted).")
    parser.add_argument(
        "--raw-ystep", type=float, default=None,
        help="Y-axis tick step for raw Average CCT mode (auto if omitted).")
    parser.add_argument(
        "--combined", action="store_true",
        help="Combine AlltoAll, RingAllreduce, and AlltoAllV (np=8, np=16) "
             "into one figure per (topology, flow_control).")
    parser.add_argument(
        "--combined-group", type=str, default="default",
        help="Combined category group id (e.g., default/1/2). "
             "When not 'default', combined mode is enabled automatically.")
    parser.add_argument(
        "--no-trimming", action="store_true",
        help="Exclude series whose recovery is Packet-trimming (IdealTrimming).")
    parser.add_argument(
        "--all-combos", action="store_true",
        help="Disable INCLUDE_COMBOS filter; plot every (lb, recovery, cc) series.")
    args = parser.parse_args()
    if args.combined_group != "default":
        args.combined = True

    global _COMBO_FILTER_ENABLED
    _COMBO_FILTER_ENABLED = not args.all_combos

    input_path = args.input_path
    if os.path.isfile(input_path):
        json_files = [input_path]
        output_dir = args.output_dir or os.path.dirname(input_path) or "."
    elif os.path.isdir(input_path):
        json_files = sorted(glob.glob(
            os.path.join(input_path, "JCT_VS_GROUPSIZE_*.json")))
        output_dir = args.output_dir or input_path
        if not json_files:
            print(f"No JCT_VS_GROUPSIZE_*.json files found in: {input_path}")
            return
    else:
        print(f"Error: not a valid file or directory: {input_path}")
        return

    os.makedirs(output_dir, exist_ok=True)
    print(f"Found {len(json_files)} file(s). Output dir: {output_dir}"
          + (" [DCQCN only]" if args.dcqcn_only else "")
          + (" [Normalized]" if args.normalize else "")
          + (" [Combined]" if args.combined else "")
          + (f" [CombinedGroup={args.combined_group}]" if args.combined else "")
          + (" [no trimming]" if args.no_trimming else ""))

    if args.combined:
        groups = _group_by_topo_fc(json_files)
        for (topo, fc), workload_data in sorted(groups.items()):
            print(f"--- combined | {topo} | {fc} ---")
            draw_combined(topo, fc, workload_data, output_dir,
                          args.dcqcn_only, args.normalize,
                          args.raw_ytop, args.raw_ystep,
                          args.no_trimming, args.combined_group)
    else:
        for jf in json_files:
            print(f"--- {os.path.basename(jf)} ---")
            draw_one_file(jf, output_dir,
                          args.dcqcn_only, args.normalize,
                          args.raw_ytop, args.raw_ystep,
                          args.no_trimming)

    print("Done.")


if __name__ == "__main__":
    main()
