import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

try:
    import lib.py.plot.plot as plot
except ImportError:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import lib.py.plot.plot as plot


BUFFER_STYLES = {
    "0.31": {"color": "#a00000", "marker": "o"},
    "0.32": {"color": "#00a000", "marker": "s"},
    "0.44": {"color": "#5060d0", "marker": "^"},
    "0.50": {"color": "#f25900", "marker": "D"},
}

BANDWIDTH_DASHES = {
    "100G": (4, 2),
    "400G": (2, 0),
}


def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num / 1000:.1f}K"
    if num < 10000:
        return f"{num / 1000:.1f}K"
    if num < 1000000:
        return f"{num / 1000:.0f}K"
    return f"{num / 1000000:.1f}M"


def sanitize_filename(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def source_category(source_file):
    return re.sub(r"__bufsz_[0-9.]+\.json$", "", source_file)


def parse_source_identity(source_file):
    match = re.match(
        r"^(.*)_(100G|400G)_OS\d+__(Lossless|Lossy)__bufsz_([0-9.]+)\.json$",
        source_file or "",
    )
    if not match:
        category = source_category(source_file or "unknown")
        return {
            "group_key": category,
            "topology_family": category,
            "bandwidth": None,
            "flow_control": None,
            "buffer_size": None,
        }
    return {
        "group_key": f"{match.group(1)}__{match.group(3)}",
        "topology_family": match.group(1),
        "bandwidth": match.group(2),
        "flow_control": match.group(3),
        "buffer_size": match.group(4),
    }


def buffer_sort_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def build_plot_groups(data):
    combine_groups = {}
    for variant in data.get("variants", []):
        identity = parse_source_identity(variant.get("source_file", "unknown"))
        combine_groups.setdefault(identity["group_key"], set())
        if identity["bandwidth"]:
            combine_groups[identity["group_key"]].add(identity["bandwidth"])

    groups = {}
    for variant in data.get("variants", []):
        identity = parse_source_identity(variant.get("source_file", "unknown"))
        use_combined_group = len(combine_groups.get(identity["group_key"], set())) > 1
        category = identity["group_key"] if use_combined_group else source_category(variant.get("source_file", "unknown"))
        bucket = groups.setdefault(
            category,
            {
                "x_tick_labels": None,
                "lines": [],
            },
        )
        for series in variant.get("data_series", []):
            x_tick_labels = series.get("flow_size_buckets_bytes", [])
            if bucket["x_tick_labels"] is None and x_tick_labels:
                bucket["x_tick_labels"] = x_tick_labels
            buffer_size = series.get("buffer_size") or variant.get("buffer_size") or "unknown"
            label = f"buf={buffer_size}"
            if use_combined_group and identity["bandwidth"]:
                label = f"{identity['bandwidth']} buf={buffer_size}"
            bucket["lines"].append(
                {
                    "label": label,
                    "bandwidth": identity["bandwidth"],
                    "buffer_size": str(buffer_size),
                    "avg": series.get("avg_fct_slowdown", []),
                    "p99": series.get("p99_fct_slowdown", []),
                }
            )

    for bucket in groups.values():
        bucket["lines"].sort(
            key=lambda line: (
                0 if line.get("bandwidth") == "100G" else 1 if line.get("bandwidth") == "400G" else 2,
                buffer_sort_key(line["buffer_size"]),
            )
        )
    return groups


def draw_metric(lines, x_tick_labels, ylabel, value_key, output_path, title):
    x_tick_positions = range(len(x_tick_labels))
    xtick_labels_shown = [
        format_bytes(x) if i % 2 == 0 or i == len(x_tick_labels) - 1 else ""
        for i, x in enumerate(x_tick_labels)
    ]
    gamma = 0.001

    p = plot.LinePointPlot()
    for line in lines:
        y_values = line[value_key]
        num_points = len(y_values)
        mark_every = list(range(0, num_points, 2))
        if num_points and num_points - 1 not in mark_every:
            mark_every.append(num_points - 1)
        buffer_style = BUFFER_STYLES.get(line["buffer_size"], {"color": "#000000", "marker": "o"})
        bandwidth = line.get("bandwidth")
        line_style = {
            "dashes": BANDWIDTH_DASHES.get(bandwidth, BANDWIDTH_DASHES["400G"]),
        }
        if bandwidth == "100G":
            line_style["linewidth"] = 4
        p.plot(
            x_tick_positions,
            y_values,
            label=line["label"],
            markevery=mark_every,
            color=buffer_style["color"],
            marker=buffer_style["marker"],
            markerfacecolor="None",
            dashes=line_style["dashes"],
            linewidth=line_style.get("linewidth", 3),
        )

    p.ax.set_title(title, fontsize=24)
    p.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
    p.ax.set_ylabel(ylabel, fontsize=34)
    p.ax.set_yscale(
        "function",
        functions=(lambda x: np.power(x, gamma), lambda y: np.power(y, 1 / gamma)),
    )
    p.ax.set_xticks(list(x_tick_positions))
    p.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha="center", fontsize=26)
    p.ax.tick_params(axis="y", labelsize=26)
    legend = p.ax.legend(fontsize=20)
    legend.set_zorder(100)

    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def draw_json_file(json_path, output_dir):
    with open(json_path, "r") as f:
        data = json.load(f)

    group = data.get("group", {})
    lb_mode = group.get("load_balancing_mode", "unknown")
    recovery = group.get("recovery_mechanism", "unknown")
    plot_groups = build_plot_groups(data)
    if not plot_groups:
        print(f"⚠️ {json_path} has no plottable variants")
        return

    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(json_path))[0]
    for category, bucket in sorted(plot_groups.items()):
        x_tick_labels = bucket["x_tick_labels"]
        lines = bucket["lines"]
        if not x_tick_labels or not lines:
            print(f"⚠️ {base_name}/{category} has incomplete plotting data")
            continue
        safe_category = sanitize_filename(category)
        title = f"{lb_mode}({recovery}) - {category}"
        avg_path = os.path.join(output_dir, f"{base_name}__{safe_category}_avg.pdf")
        p99_path = os.path.join(output_dir, f"{base_name}__{safe_category}_p99.pdf")
        draw_metric(lines, x_tick_labels, "Average FCT Slowdown", "avg", avg_path, title)
        draw_metric(lines, x_tick_labels, "P99 FCT Slowdown", "p99", p99_path, title)
        print(f"✅ saved: {avg_path}")
        print(f"✅ saved: {p99_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot FCT curves from json-data-fct-lb-recovery-grouped JSON files."
    )
    parser.add_argument("input_path", type=str, help="Input JSON file or directory")
    args = parser.parse_args()

    input_path = os.path.abspath(os.path.expanduser(args.input_path.strip()))
    if os.path.isfile(input_path):
        draw_json_file(input_path, os.path.dirname(input_path))
        return

    if os.path.isdir(input_path):
        json_files = sorted(glob.glob(os.path.join(input_path, "*.json")))
        if not json_files:
            print(f"⚠️ no json files found in {input_path}")
            return
        for json_file in json_files:
            draw_json_file(json_file, input_path)
        return

    print(f"❌ invalid input path: {input_path}")


if __name__ == "__main__":
    main()
