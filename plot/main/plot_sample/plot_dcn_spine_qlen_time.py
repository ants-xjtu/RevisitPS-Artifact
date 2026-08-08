#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import matplotlib.pyplot as plt
import os
import glob
import numpy as np

import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"


def _apply_plot_style(ax, legend=None):
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.tick_params(axis="both", which="both", colors="black", labelsize=30)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("black")
        label.set_fontfamily(FONT_FAMILY)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("black")
    ax.grid(False, axis="x")
    ax.grid(True, axis="y", alpha=0.3)
    if legend is not None:
        legend.get_frame().set_edgecolor("dimgray")
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_alpha(1.0)
        for txt in legend.get_texts():
            txt.set_fontfamily(FONT_FAMILY)
            txt.set_color("black")


def draw_avg_qlen_bar_plot(json_path, output_prefix):
    """
    计算每种算法的 Ingress/Egress 平均队列长度，并绘制分组柱状图。
    """
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"❌ 读取或解析文件 {json_path} 时出错: {e}")
        return

    metadata = data.get("metadata", {})
    data_series_list = data.get("data_series", [])

    if not data_series_list:
        print(f"⚠️ 在文件 {json_path} 中未找到 'data_series'。跳过。")
        return

    desired_order = [
        "ECMP(NAK+GBN)",
        "ConWeave(NAK+GBN)",
        "DRILL(RTO+GBN)",
        "RPS(RTO+GBN)",
        "AR(RTO+GBN)",
    ]

    series_to_plot = []
    for desired_label in desired_order:
        found_series = None
        for series in data_series_list:
            current_label = f"{series.get('load_balancing_mode', 'N/A')}({series.get('recovery_mechanism', 'N/A')})"
            if current_label == desired_label:
                found_series = series
                break
        if found_series:
            series_to_plot.append(found_series)
        else:
            print(f"⚠️ 警告: 在 {os.path.basename(json_path)} 中找不到標籤 '{desired_label}'，將跳過此項。")

    if not series_to_plot:
        print("❌ 没有可绘制的数据，跳过。")
        return

    labels = []
    egress_means_kb = []

    for series in series_to_plot:
        lb = series.get('load_balancing_mode', 'N/A')
        labels.append(lb)

        ingress_ts = (series.get("ingress_data") or {}).get("time_series", {})
        egress_ts = (series.get("egress_data") or {}).get("time_series", {})

        egress_vals = egress_ts.get("avg_qlen_bytes", []) if egress_ts else []

        egress_means_kb.append(np.mean(egress_vals) / 1024.0 if egress_vals else 0.0)

    p = plot.BarPlot()
    p.total_bar_width = 0.7
    bar_containers = []
    for lb, val in zip(labels, egress_means_kb):
        p.insert_yvals([val], label=lb)
    bar_containers = p.plot(xlabels=[""])

    fig = p.fig
    ax = p.ax
    fig.set_size_inches(9.6, 6)

    for container in bar_containers:
        patch = container.patches[0]
        patch.set_linewidth(1.2)

    ax.set_ylabel("Queue Length (KB)", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    ax.set_xlabel("", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    ax.set_ylim(0, 150)
    ax.set_xticks([])
    ax.set_xticklabels([])
    legend = ax.legend(
        loc="best",
        ncol=1,
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
    )
    _apply_plot_style(ax, legend)

    fig.tight_layout(pad=0.8)
    out_path = f"{output_prefix}_avg_qlen_bar.pdf"
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    print(f"✅ 平均队列长度柱状图已保存至: {out_path}")



def main():
    parser = argparse.ArgumentParser(
        description="从 JSON 文件绘制 Ingress/Egress 平均队列长度柱状图。"
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="输入路径：可以是单个 JSON 文件，或包含多个 JSON 文件的目录。"
    )
    args = parser.parse_args()
    input_path = args.input_path

    if os.path.isfile(input_path):
        json_files = [input_path]
    elif os.path.isdir(input_path):
        json_files = sorted(glob.glob(os.path.join(input_path, '*.json')))
        if not json_files:
            print(f"⚠️ 在目录 {input_path} 中未找到 .json 文件。")
            return
    else:
        print(f"❌ 错误: {input_path} 不是一个有效的文件或目录。")
        return

    print(f"找到 {len(json_files)} 个 JSON 文件。开始处理...")
    for json_file in json_files:
        dir_name = os.path.dirname(json_file)
        base_name = os.path.splitext(os.path.basename(json_file))[0]
        output_prefix = os.path.join(dir_name, base_name)

        print(f"\n--- 正在处理 {json_file} ---")
        draw_avg_qlen_bar_plot(json_file, output_prefix)

    print("\n✅ 所有文件处理完毕！")


if __name__ == '__main__':
    main()
