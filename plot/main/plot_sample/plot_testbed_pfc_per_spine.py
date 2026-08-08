#!/usr/bin/python3
"""
Per-Spine TRANSMIT PFC Pause Comparison

Parses TRANSMIT PAUSE STATISTICS (1us count per priority) from PFC report
text files, extracts Pri0 counts for ports 17/0, 19/0, 21/0, 23/0, 25/0,
27/0, 29/0, 31/0 (labeled as spine 1..8), and draws a grouped bar chart
comparing two schemes (e.g. ECMP vs RPS).
"""

import argparse
import os
import re
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, FuncFormatter

import lib.py.plot.plot as plot


# Ports that map to spine 1..8 on the x-axis.
SPINE_PORTS = ["17/0", "19/0", "21/0", "23/0", "25/0", "27/0", "29/0", "31/0"]


def parse_transmit_pri0(path):
    """Return {port_str: pri0_count} parsed from TRANSMIT PAUSE STATISTICS."""
    with open(path, "r") as f:
        lines = f.readlines()

    in_tx = False
    counts = {}
    for line in lines:
        if "TRANSMIT PAUSE STATISTICS" in line:
            in_tx = True
            continue
        if "RECEIVE PAUSE STATISTICS" in line:
            in_tx = False
            continue
        if not in_tx:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("Port"):
            continue

        # Token 0: "p/0", token 1: dev port, token 2: Pri0, ...
        tokens = stripped.split()
        if len(tokens) < 3:
            continue
        port = tokens[0]
        if not re.match(r"^\d+/\d+$", port):
            continue
        pri0_str = tokens[2].replace(",", "")
        try:
            pri0 = int(pri0_str)
        except ValueError:
            continue
        counts[port] = pri0
    return counts


def draw_pfc_per_spine(input_files, labels, output_path):
    series = []
    for path, label in zip(input_files, labels):
        counts = parse_transmit_pri0(path)
        ys = [counts.get(port, 0) for port in SPINE_PORTS]
        series.append((label, ys))
        missing = [port for port in SPINE_PORTS if port not in counts]
        if missing:
            print(f"  Warning: ports not found in {path}: {missing}")

    p = plot.BarPlot()
    p.fig.set_size_inches(14, 7)
    ax = p.ax
    ax.set_xlabel("Spine ID", fontsize=35)
    ax.set_ylabel("PFC Pauses", fontsize=32)

    for label, ys in series:
        p.insert_yvals(ys, label=label)

    xlabels = [str(i + 1) for i in range(len(SPINE_PORTS))]
    p.plot(xlabels=xlabels)

    ax.tick_params(axis="x", labelsize=26)
    ax.tick_params(axis="y", labelsize=26)

    yticks = [i * 40_000_000 for i in range(0, 6)]
    ax.set_ylim(0, yticks[-1])
    ax.yaxis.set_major_locator(FixedLocator(yticks))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v / 1_000_000)}M"))

    legend = ax.legend(fontsize=22, loc="best", ncol=1, borderaxespad=0.3)
    legend.set_zorder(200)

    plt.savefig(output_path, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {output_path}")


def _default_label(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return name.replace("_pfc", "").upper()


def main():
    parser = argparse.ArgumentParser(
        description="Plot per-spine TRANSMIT PFC pauses (Pri0) from PFC report text files.")
    parser.add_argument(
        "input_files", nargs="+",
        help="PFC report text files to compare (order matches --labels).")
    parser.add_argument(
        "--labels", nargs="+", default=None,
        help="Legend labels, one per input file. Defaults to filename stem.")
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output PDF path. Defaults to ./testbed_pfc_per_spine.pdf "
             "next to the first input file.")
    args = parser.parse_args()

    if args.labels is None:
        labels = [_default_label(p) for p in args.input_files]
    else:
        if len(args.labels) != len(args.input_files):
            print("Error: --labels count must match number of input files.")
            return
        labels = args.labels

    if args.output is None:
        out_dir = os.path.dirname(args.input_files[0]) or "."
        args.output = os.path.join(out_dir, "testbed_pfc_per_spine.pdf")

    draw_pfc_per_spine(args.input_files, labels, args.output)


if __name__ == "__main__":
    main()
