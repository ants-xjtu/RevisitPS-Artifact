#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import os
import glob
import re
from collections import defaultdict

plt.rcParams["font.family"] = "DejaVu Sans"

# --- FIX ---
# Disable the LaTeX text renderer that causes errors with special characters like '&'.
# This must be set before the plot object from the custom library is created.
# -----------

# --- 拓扑映射表 ---
TOPOLOGY_MAP = {
    "leaf_spine_128_100G_OS2": "LS-2:1",
    "leaf_spine_L8_S16_100G_OS1": "LS-1:1",
    "fat_k8_100G_OS1": "FT-8"
}
# Import the project's custom plotting library
try:
    import lib.py.plot.plot as plot
except ImportError:
    print("Error: Could not import the custom plotting library.")
    print("Please ensure that the script is run from a directory where 'lib/py/plot/plot.py' is accessible.")
    exit(1)


def style_axes(ax):
    ax.xaxis.label.set_color("black")
    ax.yaxis.label.set_color("black")
    ax.tick_params(axis="both", which="both", colors="black")
    for spine in ax.spines.values():
        spine.set_color("black")


def apply_log_y_bounds(ax, all_values):
    positives = [float(v) for v in all_values if float(v) > 0 and np.isfinite(v)]
    if not positives:
        return

    bottom = 1e3
    top = 1e5

    ax.set_ylim(bottom=bottom, top=top)
    yticks = [t for t in ax.get_yticks() if np.isfinite(t) and bottom < t < top]
    yticks = sorted(set([bottom] + yticks + [top]))
    ax.set_yticks(yticks)


def normalize_lb_name(lb_raw):
    lb = str(lb_raw).strip()
    lb_upper = lb.upper()
    if lb_upper == "CONWEAVE":
        return "ConWeave"
    if lb_upper == "DRILLGROUP":
        return "DRILL"
    return lb


def draw_grouped_pfc_plot(all_series_data, xlabels_multiline, config_order, output_path, y_label):
    """
    Draws a grouped PFC comparison bar chart from aggregated data across multiple files.
    """
    p = plot.BarPlot()
    p.fig.set_size_inches(9.6, 6.0)
    
    # 插入数据系列
    all_plot_values = []
    for config in config_order:
        values = all_series_data.get(config, [0] * len(xlabels_multiline))
        all_plot_values.extend(values)
        p.insert_yvals(values, label=config)

    # 绘图
    p.plot(xlabels=xlabels_multiline)

    # y 轴对数尺度
    p.ax.set_yscale('log')
    p.ax.yaxis.set_major_formatter(mticker.LogFormatterSciNotation(base=10.0))
    apply_log_y_bounds(p.ax, all_plot_values)

    # 设置轴标签
    p.ax.set_ylabel(y_label, fontsize=35)
    p.ax.tick_params(axis='y', labelsize=30)
    p.ax.tick_params(axis='x', which='major', colors='black')
    p.ax.tick_params(axis='x', which='minor', colors='black')
    p.ax.tick_params(axis='y', which='major', colors='black')
    p.ax.tick_params(axis='y', which='minor', colors='black')
    p.ax.grid(False, axis='x', which='both')

    # x 轴标签不倾斜
    plt.xticks(rotation=0, ha='center', fontsize=30)
    style_axes(p.ax)

    # 图例
    p.ax.legend(
        fontsize=25,
        loc="best",
        ncol=2,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
        borderpad=0.25,
        labelspacing=0.25,
        columnspacing=0.8,
        handlelength=1.4,
        handletextpad=0.35,
    )

    # 自适应布局
    plt.tight_layout()

    # 保存
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.12)
    plt.close()
    print(f"✅ Grouped chart saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Draw grouped PFC comparison charts from JSON files.")
    parser.add_argument("input_path", type=str, help="Directory containing JSON files")
    args = parser.parse_args()

    if not os.path.isdir(args.input_path):
        print(f"Error: '{args.input_path}' is not a valid directory.")
        return

    json_files = glob.glob(os.path.join(args.input_path, '*.json'))
    if not json_files:
        print(f"⚠️ No .json files found in {args.input_path}")
        return
    json_files.sort()

    metrics_to_plot = {
        'total_duration_ns': 'PFC Pause Time ($\\mu$s)',
        'total_pause_count': 'Total PFC Pause Count'
    }

    all_groups = []
    group_topologies = []
    file_data_cache = {}

    # --- 预扫描 JSON 文件 ---
    print(f"Found {len(json_files)} JSON file(s). Pre-scanning for configurations...")
    for json_file in json_files:
        with open(json_file, 'r') as f:
            data = json.load(f)
            file_data_cache[json_file] = data

        metadata = data.get("metadata", {})
        topo_raw = metadata.get('topology', 'N/A')
        topo_display = TOPOLOGY_MAP.get(topo_raw, topo_raw)
        group_topologies.append(topo_display)

        load_type = metadata.get('load_type', 'Unknown')
        group_label = re.sub(r'(2015|2019|2022)$', '', load_type)
        all_groups.append(group_label)

    # --- 配置顺序，去掉 LetFlow ---
    config_order = ["ECMP", "ConWeave", "DRILL", "RPS", "AR"]

    # workload 名称映射
    workload_map = {
        "Solar": "RPC",
        "AliStorage": "Storage",
        "FbHdp": "Hadoop"
    }

    print("Aggregating data and generating plots...")
    for metric_key, y_label in metrics_to_plot.items():
        series_data_for_metric = defaultdict(list)
        for json_file in json_files:
            data = file_data_cache[json_file]
            values_in_file = {}
            for series in data.get("data_series", []):
                config_label = normalize_lb_name(series.get("load_balancing_mode", "N/A"))
                # 跳过 LetFlow
                if config_label.upper() in {"LETFLOW", "CONGA"}:
                    continue
                value = series.get('pfc_stats', {}).get(metric_key, 0) / 1000.0
                values_in_file[config_label] = value

            # 填充每个配置的数据
            for config in config_order:
                series_data_for_metric[config].append(values_in_file.get(config, 0))

        # 替换 workload 名称
        all_groups_mapped = [workload_map.get(label, label) for label in all_groups]
        xlabels_multiline = [f"{topo}\n{label}" for topo, label in zip(group_topologies, all_groups_mapped)]

        output_filename = f"grouped_pfc_comparison_{metric_key}.pdf"
        output_path = os.path.join(args.input_path, output_filename)

        draw_grouped_pfc_plot(
            series_data_for_metric,
            xlabels_multiline,
            config_order,
            output_path,
            y_label
        )

    print("\n✅ All files processed successfully!")


if __name__ == '__main__':
    main()
