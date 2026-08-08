#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from matplotlib.ticker import ScalarFormatter

# 导入项目提供的绘图函数库
import lib.py.plot.plot as plot

# =======================
# 定义绘图顺序列表
# =======================
desired_order_for_pfc = [
    "ECMP",
    "ConWeave",
    "DRILL",
    "RPS",
    "AR",
]

workload_name_map = {
    "AliStorage2019": "Storage",
    "FbHdp2015": "Hadoop",
    "Solar2022": "RPC",
}

CDF_LINEWIDTH = 6.0

series_styles = {
    "Storage": {"color": "#1f77b4", "linestyle": "-"},
    "Hadoop": {"color": "#ff7f0e", "linestyle": "-"},
    "RPC": {"color": "#2ca02c", "linestyle": "-"},
    "A2Av-8": {"color": "#d62728", "linestyle": "-"},
    "A2Av-16": {"color": "#9467bd", "linestyle": "--"},
    "A2Av-32": {"color": "#8c564b", "linestyle": "-."},
    "A2Av-64": {"color": "#e377c2", "linestyle": ":"},
    "A2Av-128": {"color": "#7f7f7f", "linestyle": "--"},
}

series_label_order = {
    "Hadoop": 0,
    "RPC": 1,
    "Storage": 2,
    "A2Av-8": 3,
    "A2Av-16": 4,
    "A2Av-32": 5,
    "A2Av-64": 6,
    "A2Av-128": 7,
}

def series_mode_label(series):
    return series.get("load_balancing_mode", "N/A")

def series_workload_label(series, include_mode=False):
    workload = series.get("workload")
    label = workload_name_map.get(workload, workload or "")
    groupsize = series.get("groupsize")
    if workload == "AlltoallV" and groupsize not in (None, ""):
        label = f"A2Av-{groupsize}"
    if groupsize not in (None, ""):
        if workload != "AlltoallV":
            label = f"{label}-g{groupsize}" if label else f"g{groupsize}"
    if include_mode:
        return f"{label} {series_mode_label(series)}".strip()
    return label or series_mode_label(series)


def keep_selected_alltoallv_groups(series):
    if series.get("workload") != "AlltoallV":
        return True
    return str(series.get("groupsize")) in {"8", "32", "128"}

def series_plot_kwargs(series, include_mode=False):
    label = series_workload_label(series, include_mode=include_mode)
    style = series_styles.get(label, {})
    return {
        "label": label,
        "linewidth": CDF_LINEWIDTH,
        **style,
    }


def apply_plot_style(cdf_plot, xlabel):
    cdf_plot.fig.set_size_inches(9.6, 6)
    ax = cdf_plot.ax
    ax.set_xlabel(xlabel, fontsize=35, color="black", fontfamily="DejaVu Sans")
    ax.set_ylabel("CDF", fontsize=35, color="black", fontfamily="DejaVu Sans")
    ax.tick_params(
        axis="both",
        which="major",
        labelsize=30,
        color="black",
        labelcolor="black",
    )
    ax.tick_params(
        axis="both",
        which="minor",
        color="black",
        labelcolor="black",
    )
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily("DejaVu Sans")
    for spine in ax.spines.values():
        spine.set_color("black")
    legend = ax.legend(
        fontsize=25,
        loc="best",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
    )
    for text in legend.get_texts():
        text.set_fontfamily("DejaVu Sans")
        text.set_color("black")


def save_figure(fig, output_path):
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.18, top=0.97)
    fig.savefig(output_path, pad_inches=0.08)

def _groupsize_sort_key(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**12

def sort_series_by_desired_order(data_series_list, desired_order):
    """根据 desired_order 排序；同一算法/恢复模式下保留所有 workload/groupsize 曲线。"""
    order_map = {label: i for i, label in enumerate(desired_order)}
    series_to_plot = [
        s for s in data_series_list
        if series_mode_label(s) in order_map
    ]
    series_to_plot.sort(
        key=lambda s: (
            order_map[series_mode_label(s)],
            series_label_order.get(series_workload_label(s), 10**6),
            series_workload_label(s),
        )
    )
    if not series_to_plot:
        print("❌ 错误: 根据 desired_order 没有找到任何可绘制的系列。")
    return series_to_plot

def load_pfc_json(json_path):
    try:
        with open(json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {json_path}")
    except json.JSONDecodeError:
        print(f"❌ 错误: 无法解析 JSON 文件 {json_path}")
    return None

def merge_pfc_json_files(json_paths):
    merged = {
        "metadata": {
            "description": "Merged PFC Incast data for plotting."
        },
        "data_series": [],
    }
    seen = set()
    for json_path in json_paths:
        data = load_pfc_json(json_path)
        if not data:
            continue
        for series in data.get("data_series", []):
            dedupe_key = (
                series.get("workload"),
                series.get("groupsize"),
                series.get("topology"),
                series.get("network_load"),
                series.get("flow_control"),
                series.get("load_balancing_mode"),
                series.get("recovery_mechanism"),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged["data_series"].append(series)
    return merged

def draw_pfc_plots_from_data(data, output_prefix, source_name, series_filter=None):
    """
    从单个 JSON 文件为 PFC incast 数据绘制三张独立的 CDF 图表，并输出为 PDF。
    - Incast Flows per Event
    - Incast IPs per Event
    - Queue Bytes per Event
    """
    metadata = data.get("metadata", {})
    data_series_list = data.get("data_series", [])
    if series_filter is not None:
        data_series_list = [s for s in data_series_list if series_filter(s)]
    if not data_series_list:
        print(f"⚠️ 在 {source_name} 中找不到有效的 'data_series'。")
        return

    plt.rcParams["font.family"] = "DejaVu Sans"

    # 根据 desired_order 排序 series
    series_to_plot = sort_series_by_desired_order(data_series_list, desired_order_for_pfc)
    if not series_to_plot:
        return  # 没有可绘制的系列，直接返回
    include_mode_in_label = len({series_mode_label(s) for s in series_to_plot}) > 1

    # ===============================
    # 1. 绘制 Incast Flows 的 CDF 图
    # ===============================
    p_flows = plot.CDFPlot()
    has_flow_data = False
    for series in series_to_plot:
        flow_data = series.get("raw_data_for_cdf", {}).get("incast_flows_per_event", [])
        if not flow_data:
            continue
        has_flow_data = True
        p_flows.plot(flow_data, **series_plot_kwargs(series, include_mode=include_mode_in_label))

    if has_flow_data:
        apply_plot_style(p_flows, "Incast Flows / PFC Event")
        p_flows.ax.set_xscale('linear')
        output_path_flows = f"{output_prefix}_incast_flows.pdf"
        save_figure(p_flows.fig, output_path_flows)
        plt.close()
        print(f"✅ Incast Flows CDF 图表已保存至: {output_path_flows}")
    else:
        print(f"ℹ️ 在 {source_name} 中没有找到 Incast Flows 的数据，跳过绘图.")

    # ===============================
    # 2. 绘制 Incast IPs 的 CDF 图
    # ===============================
    p_ips = plot.CDFPlot()
    has_ip_data = False
    for series in series_to_plot:
        ip_data = series.get("raw_data_for_cdf", {}).get("incast_ips_per_event", [])
        if not ip_data:
            continue
        has_ip_data = True
        p_ips.plot(ip_data, **series_plot_kwargs(series, include_mode=include_mode_in_label))

    if has_ip_data:
        apply_plot_style(p_ips, "Number of Incast IPs per PFC Event")
        p_ips.ax.set_xscale('linear')
        output_path_ips = f"{output_prefix}_incast_ips.pdf"
        save_figure(p_ips.fig, output_path_ips)
        plt.close()
        print(f"✅ Incast IPs CDF 图表已保存至: {output_path_ips}")
    else:
        print(f"ℹ️ 在 {source_name} 中没有找到 Incast IPs 的数据，跳过绘图.")

    # ===============================
    # 3. 绘制 Queue Bytes 的 CDF 图
    # ===============================
    p_queue = plot.CDFPlot()
    has_queue_data = False
    for series in series_to_plot:
        queue_data = series.get("raw_data_for_cdf", {}).get("queue_bytes_per_event", [])
        if not queue_data:
            continue
        has_queue_data = True
        # 转换为 MB
        queue_data_mb = [x / (1024*1024) for x in queue_data]
        p_queue.plot(queue_data_mb, **series_plot_kwargs(series, include_mode=include_mode_in_label))

    if has_queue_data:
        apply_plot_style(p_queue, "Queue Size (MB) / PFC Event")
        p_queue.ax.set_xscale('linear')
        p_queue.ax.xaxis.set_major_formatter(ScalarFormatter())
        p_queue.ax.ticklabel_format(style='plain', axis='x')
        output_path_queue = f"{output_prefix}_queue_bytes.pdf"
        save_figure(p_queue.fig, output_path_queue)
        plt.close()
        print(f"✅ Queue Bytes CDF 图表已保存至: {output_path_queue}")
    else:
        print(f"ℹ️ 在 {source_name} 中没有找到 Queue Bytes 的数据，跳过绘图.")

def draw_pfc_plots(json_path, output_prefix):
    data = load_pfc_json(json_path)
    if not data:
        return
    draw_pfc_plots_from_data(
        data,
        output_prefix,
        json_path,
        series_filter=keep_selected_alltoallv_groups,
    )

def main():
    parser = argparse.ArgumentParser(
        description="从 JSON 档案或目录绘制 PFC Incast 事件的 CDF 图表"
    )
    parser.add_argument(
        "input_paths",
        type=str,
        nargs="+",
        help="输入路径，可以是单个 JSON 文件、多个 JSON 文件，或一个包含多个 JSON 文件的目录。"
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="多个 JSON 文件合并绘图时的输出前缀。"
    )
    args = parser.parse_args()

    if len(args.input_paths) > 1:
        json_files = args.input_paths
        invalid_paths = [p for p in json_files if not os.path.isfile(p)]
        if invalid_paths:
            print(f"❌ 错误: 以下路径不是有效 JSON 文件: {invalid_paths}")
            return
        output_prefix = args.output_prefix
        if output_prefix is None:
            output_dir = os.path.dirname(json_files[0])
            output_prefix = os.path.join(output_dir, "combined_pfc_incast")
        print(f"--- 正在合并处理 {len(json_files)} 个 JSON 文件 ---")
        merged_data = merge_pfc_json_files(json_files)
        draw_pfc_plots_from_data(
            merged_data,
            output_prefix,
            ", ".join(json_files),
            series_filter=keep_selected_alltoallv_groups,
        )

    elif os.path.isfile(args.input_paths[0]):
        # 单文件模式
        json_file = args.input_paths[0]
        base_name = os.path.basename(json_file)
        output_dir = os.path.dirname(json_file)
        output_prefix = args.output_prefix or os.path.join(
            output_dir, os.path.splitext(base_name)[0]
        )
        print(f"--- 正在处理 {json_file} ---")
        draw_pfc_plots(json_file, output_prefix)

    elif os.path.isdir(args.input_paths[0]):
        # 目录模式
        json_files = glob.glob(os.path.join(args.input_paths[0], '*.json'))
        if not json_files:
            print(f"⚠️ 在目录 {args.input_paths[0]} 中没有找到任何 .json 档案。")
            return
        print(f"找到 {len(json_files)} 个 JSON 档案，开始处理...")
        for json_file in json_files:
            base_name = os.path.basename(json_file)
            output_prefix = os.path.join(
                args.input_paths[0], os.path.splitext(base_name)[0]
            )
            print(f"--- 正在处理 {json_file} ---")
            draw_pfc_plots(json_file, output_prefix)
        print("✅ 所有档案处理完毕！")
    else:
        print(f"❌ 错误: {args.input_paths[0]} 不是有效的档案或目录。")
        return

if __name__ == '__main__':
    main()
