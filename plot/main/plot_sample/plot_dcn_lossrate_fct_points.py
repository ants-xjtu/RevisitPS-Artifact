#!/usr/bin/python3

import argparse
import json
import os

import matplotlib.pyplot as plt
import numpy as np


plt.rcParams["font.family"] = "DejaVu Sans"

LINE_STYLES = [
    {"color": "#a00000", "marker": "o"},
    {"color": "#00a000", "marker": "s"},
    {"color": "#5060d0", "marker": "^"},
    {"color": "#f25900", "marker": "D"},
]


def style_axes(ax):
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_fontfamily("DejaVu Sans")
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_fontfamily("DejaVu Sans")
    ax.tick_params(axis="both", which="both", colors="black", labelsize=18)
    for spine in ax.spines.values():
        spine.set_color("black")
        spine.set_visible(True)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("black")
        label.set_fontfamily("DejaVu Sans")
    ax.grid(True, axis="x", alpha=0.25)
    ax.grid(True, axis="y", alpha=0.25)


def nice_bounds(values):
    ymin = min(values)
    ymax = max(values)
    span = ymax - ymin
    if span <= 0:
        span = max(1.0, ymax * 0.1)
    bottom = max(0, ymin - span * 0.18)
    top = ymax + span * 0.18
    return bottom, top


def draw_one_series(series, style, output_path):
    fig, ax = plt.subplots(figsize=(9.6, 6))
    loss_rates = np.array(series["loss_rates"], dtype=float)
    values = np.array(series["values"], dtype=float)

    ax.plot(
        loss_rates,
        values,
        label=series["title"],
        linewidth=3,
        markersize=8,
        markerfacecolor="white",
        markeredgewidth=2,
        **style,
    )
    ax.set_xscale("log")
    ax.set_xlim(7e-6, 4e-1)
    ax.set_xticks([1e-5, 1e-4, 1e-3, 1e-2, 1e-1])
    ax.set_xticklabels(["1e-5", "1e-4", "1e-3", "1e-2", "1e-1"])
    ax.set_xlabel("Loss Rate", fontsize=22)
    ax.set_ylabel(series.get("ylabel", "FCT (us)"), fontsize=22)
    bottom, top = nice_bounds(values)
    ax.set_ylim(bottom, top)
    style_axes(ax)
    ax.legend(
        fontsize=25,
        prop={"family": "DejaVu Sans", "size": 25},
        loc="best",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
    )

    fig.tight_layout(pad=1.0)
    fig.savefig(output_path, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Plot FCT-vs-loss-rate points from a JSON file."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "dcn_lossrate_fct_points.json"),
        help="Input JSON file. Defaults to dcn_lossrate_fct_points.json next to this script.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output PDF path. Defaults to <input_basename>.pdf",
    )
    args = parser.parse_args()

    input_json = os.path.abspath(os.path.expanduser(args.input_json))
    with open(input_json, "r") as f:
        data = json.load(f)

    if args.output:
        output_path = os.path.abspath(os.path.expanduser(args.output))
    else:
        output_path = os.path.splitext(input_json)[0] + ".pdf"
    output_dir = os.path.dirname(output_path) or os.path.dirname(input_json)
    output_base = os.path.splitext(os.path.basename(output_path))[0]

    for idx, series in enumerate(data["series"]):
        out_path = os.path.join(output_dir, f"{output_base}_{series['key']}.pdf")
        draw_one_series(series, LINE_STYLES[idx % len(LINE_STYLES)], out_path)
        print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
