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
from matplotlib.lines import Line2D
import numpy as np

import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"
Y_LABEL_FONTSIZE = 35
X_LABEL_FONTSIZE = 35
X_TICK_FONTSIZE = 30
Y_TICK_FONTSIZE = 30
LEGEND_FONTSIZE = 25


# ── Display/order configuration ───────────────────────────────────────────────
LB_ORDER = [
    "ECMP", "ConWeave", "RPS", "AR", "DRILL", "SGLB",
    "LetFlow", "CONGA",
]
CC_ORDER = ["DCQCN", "NONE"]

# timeout_mode is the source of truth for the "+1/N" suffix: any recovery
# paired with timeout_mode=N (N != "0") renders as "<recovery>+1/N". An
# existing "+1/M" already baked into recovery_mechanism is stripped first
# so timeout_mode wins (avoids e.g. "RTO+GBN+1/2+1/2").
import re as _re
_TIMEOUT_SUFFIX_RE = _re.compile(r"\+1/\d+$")


# Combined-mode x-axis categories: (load_type, group_size, display_label).
COMBINED_CATEGORIES = [
    ("Alltoall", 8, "AlltoAll"),
    ("RingAllreduce", 8, "RingAllreduce"),
    ("AlltoallV", 8, "AlltoAllV-8"),
    ("AlltoallV", 16, "AlltoAllV-16"),
    ("AlltoallV", 32, "AlltoAllV-32"),
    ("AlltoallV", 64, "AlltoAllV-64"),
    ("AlltoallV", 128, "AlltoAllV-128"),
]

# By-scenario mode: match topology substring -> (label, order).
SCENARIO_MATCHERS = [
    ("AsymFail1pct",         "S1"),
    ("AsymFail10pct",        "S2"),
    ("AsymBw10pct_R0.5",     "S3"),
    ("AsymBw20pct_R0.5",     "S4"),
]


def _scenario_of(topo):
    for sub, label in SCENARIO_MATCHERS:
        if sub in topo:
            return label
    return None


# (lb, recovery, cc) combos to draw, in the order they should appear on the
# plot (legend + bars). Recovery here is the effective name after merging in
# timeout_mode (e.g. timeout_mode=4 -> "...+1/4"). Comment out any row to
# drop that series. Empty list => no filter, fall back to (cc, lb, recovery).
INCLUDE_COMBOS = []


_COMBO_FILTER_ENABLED = True


def _combo_included(lb, rec, cc):
    if not _COMBO_FILTER_ENABLED or not INCLUDE_COMBOS:
        return True
    return (lb, rec, cc) in INCLUDE_COMBOS


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


def _place_legend(ax, n_items, legend_max_rows, loc="best"):
    """Single legend where column 0 is filled with up to ``legend_max_rows``
    entries before column 1 starts, and so on. Matplotlib's ``ncol`` divides
    entries evenly across columns (e.g. 6 items + ncol=2 → 3+3), so we pad
    with invisible handles to force the desired split (e.g. 6 items + pad 2 →
    4+2 with two empty slots at the bottom of col 1)."""
    if ax.legend_ is not None:
        ax.legend_.remove()

    handles, labels = ax.get_legend_handles_labels()
    total = len(labels)
    if total == 0:
        return None

    if legend_max_rows is None or legend_max_rows <= 0:
        ncol = 1
    else:
        ncol = max(1, int(math.ceil(total / legend_max_rows)))
        nrows = legend_max_rows
        pad = ncol * nrows - total
        for _ in range(pad):
            handles.append(Line2D([], [], linestyle="None", marker="None"))
            labels.append("")

    legend = ax.legend(
        handles, labels,
        fontsize=LEGEND_FONTSIZE,
        prop={"family": FONT_FAMILY, "size": LEGEND_FONTSIZE},
        loc=loc,
        ncol=ncol,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
        borderpad=0.1,
        labelspacing=0.05,
        columnspacing=0.3,
        handlelength=1.0,
        handletextpad=0.15,
    )
    legend.set_zorder(200)
    return legend


def _scenario_legend_location(load_type):
    return "upper left" if load_type == "Alltoall" else "best"


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
    if legend is not None and hasattr(legend, "get_frame"):
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
    "RTO+GBN+1/2": "RTO+GBN",
}


def _display_recovery(recovery):
    recovery = _RECOVERY_DISPLAY.get(recovery, recovery)
    # Convert "+1/N" suffix to "+0.xxx" decimal form (e.g. +1/4 -> +0.25).
    m = _TIMEOUT_SUFFIX_RE.search(recovery)
    if m:
        n = int(m.group().split("/")[-1])
        if n:
            dec_str = f"{1.0 / n:g}"
            recovery = recovery[: m.start()] + f"+{dec_str}"
    return recovery


def _is_trimming(recovery):
    return recovery.startswith("IdealTrimming")


def _lossy_filter_ok(rec, fc):
    """Per-series filter. In Lossy, drop bare RTO+GBN here is done later
    (post-collection) because it needs to know whether a +1/N variant exists
    for the same (lb, cc). This stub keeps all series through the per-series
    pass; use _drop_bare_rto_when_timeouted on the collected map instead."""
    return True


def _drop_bare_rto_when_timeouted(series_map, fc):
    """For Lossy only: when a (lb, cc) group has both bare 'RTO+GBN' and some
    'RTO+GBN+1/N' variant, drop the bare one. If only the bare exists, keep
    it. Mutates and returns series_map."""
    if str(fc).lower() != "lossy":
        return series_map
    has_timeouted = set()
    for (lb, rec, cc) in series_map.keys():
        if rec.startswith("RTO+GBN") and _TIMEOUT_SUFFIX_RE.search(rec):
            has_timeouted.add((lb, cc))
    for key in list(series_map.keys()):
        lb, rec, cc = key
        if rec == "RTO+GBN" and (lb, cc) in has_timeouted:
            del series_map[key]
    return series_map


def _display_lb(lb):
    return lb


_HIDE_RECOVERY = False
_NO_CONGA = False


def _lb_filter_ok(lb):
    if _NO_CONGA and str(lb).upper() == "CONGA":
        return False
    return True


def _series_label(lb, recovery, cc, show_cc):
    lb = _display_lb(lb)
    if _HIDE_RECOVERY:
        return f"{lb} / {cc}" if show_cc else lb
    rec = _display_recovery(recovery)
    if show_cc:
        return f"{lb}({rec}) / {cc}"
    return f"{lb}({rec})"


def _series_sort_key(key):
    if _COMBO_FILTER_ENABLED and INCLUDE_COMBOS:
        try:
            return (INCLUDE_COMBOS.index(key),)
        except ValueError:
            return (len(INCLUDE_COMBOS),)
    lb, recovery, cc = key
    lb_idx = LB_ORDER.index(lb) if lb in LB_ORDER else len(LB_ORDER)
    cc_idx = CC_ORDER.index(cc) if cc in CC_ORDER else len(CC_ORDER)
    return (cc_idx, lb_idx, recovery)


def _collect_from_file(data, dcqcn_only, no_trimming):
    """Return (sorted group_sizes, {(lb, recovery, cc): {group_size: (mean, ideal)}})."""
    fc = data.get("metadata", {}).get("flow_control", "")
    series_map = {}
    group_sizes = set()
    for series in data.get("data_series", []):
        cc = series.get("congestion_control", "?")
        if dcqcn_only and cc != "DCQCN":
            continue
        lb = series.get("load_balancing_mode", "?")
        if not _lb_filter_ok(lb):
            continue
        rec = _effective_recovery(series.get("recovery_mechanism", "?"),
                                  series.get("timeout_mode"))
        if no_trimming and _is_trimming(rec):
            continue
        if not _lossy_filter_ok(rec, fc):
            continue
        if not _combo_included(lb, rec, cc):
            continue
        key = (lb, rec, cc)
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
    _drop_bare_rto_when_timeouted(series_map, fc)
    return sorted(group_sizes), series_map


def _normalize_with_ideal(data):
    """Convert JCT_WITH_IDEAL_*.json schema (per-rank avg_jct_us + top-level
    ideal_jct_data) into the points-based schema used by the rest of the code.
    No-op if the file already has a `points` entry per series.
    """
    ideal_map = data.get("ideal_jct_data")
    if not ideal_map:
        return data
    meta = data.get("metadata", {})
    meta_gs = meta.get("group_size")
    for series in data.get("data_series", []):
        if "points" in series and series["points"]:
            continue
        ranks_jct = series.get("avg_jct_us")
        if not ranks_jct:
            continue
        gs = series.get("group_size", meta_gs)
        msg_size = str(series.get("message_size_bytes",
                                  meta.get("message_size", "")))
        ideal_entry = ideal_map.get(msg_size, {})
        ideal_val = ideal_entry.get("ideal_jct_us")
        mean_jct = sum(ranks_jct) / len(ranks_jct)
        series["points"] = [{
            "group_size": gs,
            "jct_us": mean_jct,
            "ideal_jct_us": ideal_val,
        }]
    return data


def _apply_scenario_drill_policy(data):
    topology = data.get("metadata", {}).get("topology", "")
    use_group = "AsymBw" in topology
    selected = []
    for series in data.get("data_series", []):
        lb = series.get("load_balancing_mode")
        if lb == "DRILL" and use_group:
            continue
        if lb == "DRILLGroup" and not use_group:
            continue
        if lb == "DRILLGroup":
            series = dict(series)
            series["load_balancing_mode"] = "DRILL"
        selected.append(series)
    data = dict(data)
    data["data_series"] = selected
    return data


def _group_by_topo_fc(json_files):
    """Group JSON files by (topology, flow_control) and keep per load_type."""
    groups = {}
    for jf in json_files:
        with open(jf, "r") as f:
            data = json.load(f)
        data = _apply_scenario_drill_policy(_normalize_with_ideal(data))
        meta = data.get("metadata", {})
        topo = meta.get("topology", "unknown")
        fc = meta.get("flow_control", "unknown")
        load_type = meta.get("load_type", "unknown")
        groups.setdefault((topo, fc), {})[load_type] = data
    return groups


def draw_combined(topo, fc, workload_data, output_dir, dcqcn_only, normalize,
                  raw_ytop, raw_ystep, no_trimming, legend_max_rows):
    """Draw ONE bar chart per (topology, flow_control) combining AlltoAll,
    RingAllreduce, and AlltoAllV (np=8, np=16) on the x-axis."""
    series_map = {}
    for i, (load_type, gs, _label) in enumerate(COMBINED_CATEGORIES):
        data = workload_data.get(load_type)
        if not data:
            continue
        for series in data.get("data_series", []):
            cc = series.get("congestion_control", "?")
            if dcqcn_only and cc != "DCQCN":
                continue
            lb = series.get("load_balancing_mode", "?")
            if not _lb_filter_ok(lb):
                continue
            rec = _effective_recovery(series.get("recovery_mechanism", "?"),
                                      series.get("timeout_mode"))
            if no_trimming and _is_trimming(rec):
                continue
            if not _lossy_filter_ok(rec, fc):
                continue
            if not _combo_included(lb, rec, cc):
                continue
            key = (lb, rec, cc)
            entry = series_map.setdefault(key, [None] * len(COMBINED_CATEGORIES))
            for pt in series.get("points", []):
                if pt.get("group_size") != gs:
                    continue
                mean = pt.get("jct_us")
                ideal = pt.get("ideal_jct_us")
                if mean is None:
                    continue
                val = (float(mean), float(ideal) if ideal else None)
                prev = entry[i]
                if prev is None or prev[0] > val[0]:
                    entry[i] = val

    _drop_bare_rto_when_timeouted(series_map, fc)
    if not series_map:
        print(f"  [WARN] No drawable data for {topo} / {fc}")
        return

    show_cc = not dcqcn_only
    series_keys = sorted(series_map.keys(), key=_series_sort_key)
    category_names = [name for (_, _, name) in COMBINED_CATEGORIES]

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
        label = _series_label(lb, rec, cc, show_cc)
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=category_names)

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=Y_LABEL_FONTSIZE)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=Y_LABEL_FONTSIZE)
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelsize=X_TICK_FONTSIZE)
    ax.tick_params(axis="y", labelsize=Y_TICK_FONTSIZE)

    legend = _place_legend(ax, len(series_keys), legend_max_rows)
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
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close()
    print(f"  [combined | {fc} | {topo}] -> {out_path}")


def draw_by_scenario(load_type, fc, scenario_to_data, output_dir,
                     dcqcn_only, normalize, raw_ytop, raw_ystep, no_trimming,
                     legend_max_rows):
    """One figure per (load_type, flow_control), x-axis = topology scenarios
    (S1..S4), bars = (lb, recovery, cc) series."""
    scenarios = [lbl for (_sub, lbl) in SCENARIO_MATCHERS]
    series_map = {}

    def canonical_rec(rec):
        # Fold bare 'RTO+GBN' and any 'RTO+GBN+1/N' into a single series key
        # so per-scenario we can prefer +1/N when present and fall back to
        # bare otherwise. Other recoveries keep their name.
        if rec.startswith("RTO+GBN"):
            return "RTO+GBN"
        return rec

    for i, scen in enumerate(scenarios):
        data = scenario_to_data.get(scen)
        if not data:
            continue
        # Per-scenario: remember which (lb, cc) have a +1/N variant so we
        # skip bare RTO+GBN for them.
        has_timeouted = set()
        for series in data.get("data_series", []):
            lb = series.get("load_balancing_mode", "?")
            cc = series.get("congestion_control", "?")
            rec = _effective_recovery(series.get("recovery_mechanism", "?"),
                                      series.get("timeout_mode"))
            if rec.startswith("RTO+GBN") and _TIMEOUT_SUFFIX_RE.search(rec):
                has_timeouted.add((lb, cc))

        for series in data.get("data_series", []):
            cc = series.get("congestion_control", "?")
            if dcqcn_only and cc != "DCQCN":
                continue
            lb = series.get("load_balancing_mode", "?")
            if not _lb_filter_ok(lb):
                continue
            rec = _effective_recovery(series.get("recovery_mechanism", "?"),
                                      series.get("timeout_mode"))
            if no_trimming and _is_trimming(rec):
                continue
            if rec == "RTO+GBN" and (lb, cc) in has_timeouted:
                continue
            if not _combo_included(lb, rec, cc):
                continue
            key = (lb, canonical_rec(rec), cc)
            entry = series_map.setdefault(key, [None] * len(scenarios))
            for pt in series.get("points", []):
                mean = pt.get("jct_us")
                ideal = pt.get("ideal_jct_us")
                if mean is None:
                    continue
                val = (float(mean), float(ideal) if ideal else None)
                prev = entry[i]
                if prev is None or prev[0] > val[0]:
                    entry[i] = val

    if not series_map:
        print(f"  [WARN] No drawable data for scenario view: {load_type}/{fc}")
        return

    show_cc = not dcqcn_only
    series_keys = sorted(series_map.keys(), key=_series_sort_key)

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
        label = _series_label(lb, rec, cc, show_cc)
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=scenarios)

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=Y_LABEL_FONTSIZE)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=Y_LABEL_FONTSIZE)
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelsize=X_TICK_FONTSIZE)
    ax.tick_params(axis="y", labelsize=Y_TICK_FONTSIZE)

    legend = _place_legend(
        ax,
        len(series_keys),
        legend_max_rows,
        loc=_scenario_legend_location(load_type),
    )
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

    parts = ["scenario", load_type, fc.lower(), "norm" if normalize else "avg"]
    if dcqcn_only:
        parts.append("dcqcn")
    out_path = os.path.join(output_dir, "_".join(parts) + ".pdf")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close()
    print(f"  [scenario | {load_type} | {fc}] -> {out_path}")


def _group_by_loadtype_fc_scenario(json_files):
    """Group files by (load_type, flow_control) -> {scenario_label: data}."""
    groups = {}
    for jf in json_files:
        with open(jf, "r") as f:
            data = json.load(f)
        data = _apply_scenario_drill_policy(_normalize_with_ideal(data))
        meta = data.get("metadata", {})
        topo = meta.get("topology", "")
        scen = _scenario_of(topo)
        if scen is None:
            continue
        load_type = meta.get("load_type", "unknown")
        fc = meta.get("flow_control", "unknown")
        groups.setdefault((load_type, fc), {})[scen] = data
    return groups


def draw_one_file(json_path, output_dir, dcqcn_only, normalize,
                  raw_ytop, raw_ystep, no_trimming, legend_max_rows):
    with open(json_path, "r") as f:
        data = json.load(f)
    data = _apply_scenario_drill_policy(_normalize_with_ideal(data))

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
        label = _series_label(lb, rec, cc, show_cc)
        p.insert_yvals(yvals, label=label)

    p.plot(xlabels=[str(gs) for gs in group_sizes])

    ax = p.ax
    fig = p.fig
    fig.set_size_inches(9.6, 6)

    if normalize:
        ax.set_ylabel("Normalized CCT", fontsize=Y_LABEL_FONTSIZE)
    else:
        ax.set_ylabel("Average CCT (us)", fontsize=Y_LABEL_FONTSIZE)
    ax.set_xlabel("Group Size", fontsize=X_LABEL_FONTSIZE)
    ax.tick_params(axis="x", labelsize=X_TICK_FONTSIZE)
    ax.tick_params(axis="y", labelsize=Y_TICK_FONTSIZE)

    legend = _place_legend(ax, len(series_keys), legend_max_rows)
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
    fig.tight_layout()
    fig.savefig(out_path)
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
        "--no-trimming", action="store_true",
        help="Exclude series whose recovery is Packet-trimming (IdealTrimming).")
    parser.add_argument(
        "--all-combos", action="store_true",
        help="Disable INCLUDE_COMBOS filter; plot every (lb, recovery, cc) series.")
    parser.add_argument(
        "--by-scenario", action="store_true",
        help="Plot one figure per (load_type, flow_control) with S1..S4 "
             "(Fail1/Fail10/Bw10/Bw20) scenarios as x-axis categories.")
    parser.add_argument(
        "--hide-recovery", action="store_true",
        help="Hide the recovery suffix in legend labels "
             "(e.g. 'RPS(RTO+GBN)' -> 'RPS').")
    parser.add_argument(
        "--no-conga", action="store_true",
        help="Exclude series whose load-balancing mode is CONGA.")
    parser.add_argument(
        "--legend-max-rows", type=int, default=99,
        help="Maximum legend entries per column before adding another column.")
    args = parser.parse_args()

    global _COMBO_FILTER_ENABLED, _HIDE_RECOVERY, _NO_CONGA
    _COMBO_FILTER_ENABLED = not args.all_combos
    _HIDE_RECOVERY = args.hide_recovery
    _NO_CONGA = args.no_conga

    input_path = args.input_path
    if os.path.isfile(input_path):
        json_files = [input_path]
        output_dir = args.output_dir or os.path.dirname(input_path) or "."
    elif os.path.isdir(input_path):
        json_files = sorted(
            glob.glob(os.path.join(input_path, "JCT_VS_GROUPSIZE_*.json"))
            + glob.glob(os.path.join(input_path, "JCT_WITH_IDEAL_*.json"))
        )
        output_dir = args.output_dir or input_path
        if not json_files:
            print(f"No JCT_VS_GROUPSIZE_*/JCT_WITH_IDEAL_*.json files "
                  f"found in: {input_path}")
            return
    else:
        print(f"Error: not a valid file or directory: {input_path}")
        return

    os.makedirs(output_dir, exist_ok=True)
    print(f"Found {len(json_files)} file(s). Output dir: {output_dir}"
          + (" [DCQCN only]" if args.dcqcn_only else "")
          + (" [Normalized]" if args.normalize else "")
          + (" [Combined]" if args.combined else "")
          + (" [By scenario]" if args.by_scenario else "")
          + (" [no trimming]" if args.no_trimming else ""))

    if args.by_scenario:
        groups = _group_by_loadtype_fc_scenario(json_files)
        for (load_type, fc), scen_to_data in sorted(groups.items()):
            print(f"--- scenario | {load_type} | {fc} ---")
            draw_by_scenario(load_type, fc, scen_to_data, output_dir,
                             args.dcqcn_only, args.normalize,
                             args.raw_ytop, args.raw_ystep,
                             args.no_trimming, args.legend_max_rows)
        print("Done.")
        return

    if args.combined:
        groups = _group_by_topo_fc(json_files)
        for (topo, fc), workload_data in sorted(groups.items()):
            print(f"--- combined | {topo} | {fc} ---")
            draw_combined(topo, fc, workload_data, output_dir,
                          args.dcqcn_only, args.normalize,
                          args.raw_ytop, args.raw_ystep,
                          args.no_trimming, args.legend_max_rows)
    else:
        for jf in json_files:
            print(f"--- {os.path.basename(jf)} ---")
            draw_one_file(jf, output_dir,
                          args.dcqcn_only, args.normalize,
                          args.raw_ytop, args.raw_ystep,
                          args.no_trimming, args.legend_max_rows)

    print("Done.")


if __name__ == "__main__":
    main()
