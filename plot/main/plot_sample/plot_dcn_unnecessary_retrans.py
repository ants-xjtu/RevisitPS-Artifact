import argparse
import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"

LB_ORDER = ["RPS", "AR", "DRILL", "SGLB"]
LB_DISPLAY = {lb: lb for lb in LB_ORDER}
SCENARIO_ORDER = {f"S{index}": index for index in range(1, 5)}


def format_k_ticks(value, _):
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value / 1000:.0f}K"
    return f"{value:.0f}"


def compute_ymax_with_headroom(max_value):
    if max_value <= 0:
        return 1
    padded = max_value * 1.1
    step = 10000 if padded >= 100000 else 5000 if padded >= 50000 else 1000
    return int(np.ceil(padded / step) * step)


def short_topo(topo):
    m = re.search(r"(AsymFail\d+pct|AsymBw\d+pct(?:_R[\d.]+)?)", topo)
    if not m:
        return topo
    s = m.group(1)
    s = re.sub(r"AsymFail1pct", "S1", s)
    s = re.sub(r"AsymFail10pct", "S2", s)
    s = re.sub(r"AsymBw10pct_R0\.5", "S3", s)
    s = re.sub(r"AsymBw20pct_R0\.5", "S4", s)
    return s


def style_axes(ax):
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
        spine.set_visible(True)


def reorder_legend_drop_first(ax):
    handles, labels = ax.get_legend_handles_labels()
    grouped = {}
    order = []
    for handle, label in zip(handles, labels):
        base = label.rsplit(" (", 1)[0]
        if base not in grouped:
            grouped[base] = {}
            order.append(base)
        if "(drop)" in label:
            grouped[base]["drop"] = (handle, label)
        elif "(reorder)" in label:
            grouped[base]["reorder"] = (handle, label)
        else:
            grouped[base].setdefault("other", []).append((handle, label))

    new_handles = []
    new_labels = []
    for base in order:
        for key in ("drop", "reorder"):
            if key in grouped[base]:
                h, l = grouped[base][key]
                new_handles.append(h)
                new_labels.append(l)
        for h, l in grouped[base].get("other", []):
            new_handles.append(h)
            new_labels.append(l)
    return new_handles, new_labels


def draw_unnecessary_retrans(csv_path, output_path):
    df = pd.read_csv(csv_path, skip_blank_lines=True)
    df = df.dropna(subset=["topo", "lb"])
    df["lb"] = df["lb"].astype(str).str.strip()
    scenarios = df["topo"].map(short_topo)
    df = df[
        ~((df["lb"] == "DRILL") & scenarios.isin({"S3", "S4"}))
        & ~((df["lb"] == "DRILLGroup") & scenarios.isin({"S1", "S2"}))
    ].copy()
    df.loc[df["lb"] == "DRILLGroup", "lb"] = "DRILL"

    topos = sorted(
        dict.fromkeys(df["topo"].tolist()),
        key=lambda topo: SCENARIO_ORDER.get(short_topo(topo), len(SCENARIO_ORDER)),
    )
    group_labels = [short_topo(t) for t in topos]

    vals = {lb: {"drop_count": [], "spur_count": [], "total_count": []} for lb in LB_ORDER}
    for topo in topos:
        sub = df[df["topo"] == topo]
        for lb in LB_ORDER:
            row = sub[sub["lb"] == lb]
            if row.empty:
                vals[lb]["drop_count"].append(0.0)
                vals[lb]["spur_count"].append(0.0)
                vals[lb]["total_count"].append(0.0)
            else:
                r = row.iloc[0]
                d = float(r["retx_w_drop"])
                s = float(r["retx_spurious"])
                t = d + s
                vals[lb]["drop_count"].append(d)
                vals[lb]["spur_count"].append(s)
                vals[lb]["total_count"].append(t)

    p = plot.BarPlot()

    n_topos = len(topos)
    n_lb = len(LB_ORDER)
    group_spacing = 1.6
    x_indices = np.arange(n_topos) * group_spacing
    bar_width = 0.28
    inner_gap = 0.04
    offsets = (np.arange(n_lb) - (n_lb - 1) / 2.0) * (bar_width + inner_gap)

    # Two fillstyles per LB: solid for necessary, hatched for spurious.
    # Use fillstyles[0..] cycling; pick contrasting pairs.
    solid_styles = [
        plot.fillstyles[0],   # red solid
        plot.fillstyles[9],   # green solid
        plot.fillstyles[10],  # blue solid
        plot.fillstyles[11],  # orange solid
        plot.fillstyles[12],
    ]
    hatch_styles = [
        {"edgecolor": plot.colors[0], "fill": False, "linewidth": 2, "hatch": "////"},
        {"edgecolor": plot.colors[1], "fill": False, "linewidth": 2, "hatch": "////"},
        {"edgecolor": plot.colors[2], "fill": False, "linewidth": 2, "hatch": "////"},
        {"edgecolor": plot.colors[3], "fill": False, "linewidth": 2, "hatch": "////"},
        {"edgecolor": plot.colors[4], "fill": False, "linewidth": 2, "hatch": "////"},
    ]

    for i, lb in enumerate(LB_ORDER):
        pos = x_indices + offsets[i]
        drop = np.array(vals[lb]["drop_count"])
        spur = np.array(vals[lb]["spur_count"])

        s_solid = dict(solid_styles[i])
        s_solid["label"] = f"{LB_DISPLAY[lb]} (reorder)"
        s_hatch = dict(hatch_styles[i])
        s_hatch["label"] = f"{LB_DISPLAY[lb]} (drop)"

        p.ax.bar(pos, spur, width=bar_width, capstyle="round",
                 joinstyle="round", zorder=100, **s_solid)
        p.ax.bar(pos, drop, bottom=spur, width=bar_width, capstyle="round",
                 joinstyle="round", zorder=100, **s_hatch)

    p.ax.set_ylabel("Retransmissions", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    p.ax.set_xlabel("", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    p.ax.set_xticks(x_indices)
    p.ax.set_xticklabels(group_labels, fontsize=30)
    p.ax.tick_params(axis="x", labelsize=30, colors="black")
    p.ax.tick_params(axis="y", labelsize=30, colors="black")
    max_total = max(
        max(values["total_count"], default=0)
        for values in vals.values()
    )
    p.ax.set_ylim(bottom=0, top=compute_ymax_with_headroom(max_total))
    p.ax.yaxis.set_major_formatter(mticker.FuncFormatter(format_k_ticks))
    p.ax.grid(False, axis="x")
    p.ax.grid(True, axis="y")

    legend_handles, legend_labels = reorder_legend_drop_first(p.ax)
    p.ax.legend(
        legend_handles,
        legend_labels,
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        loc="best",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
        handlelength=1.5,
        handletextpad=0.4,
        labelspacing=0.3,
    )
    style_axes(p.ax)

    p.fig.set_size_inches(9.6, 6)
    p.fig.tight_layout()

    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    print(f"✅ saved: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", help="CSV file or directory containing CSV files")
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.input_path))
    if os.path.isfile(path):
        out = os.path.join(
            os.path.dirname(path),
            "plot_" + os.path.splitext(os.path.basename(path))[0] + "_unnecessary_retrans.pdf",
        )
        draw_unnecessary_retrans(path, out)
    else:
        for f in glob.glob(os.path.join(path, "*.csv")):
            out = os.path.join(
                path,
                "plot_" + os.path.splitext(os.path.basename(f))[0] + "_unnecessary_retrans.pdf",
            )
            draw_unnecessary_retrans(f, out)


if __name__ == "__main__":
    main()
