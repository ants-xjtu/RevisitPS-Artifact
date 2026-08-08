#!/usr/bin/python3

import json
import matplotlib.pyplot as plt
import argparse
import os
import sys
from itertools import cycle

def setup_plot_style():
    """设置图表的基础样式，使其更加美观"""
    plt.style.use('ggplot')
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.titlesize'] = 14
    plt.rcParams['axes.labelsize'] = 12
    plt.rcParams['xtick.labelsize'] = 10
    plt.rcParams['ytick.labelsize'] = 10
    plt.rcParams['legend.fontsize'] = 10
    plt.rcParams['lines.linewidth'] = 2
    plt.rcParams['lines.markersize'] = 6

def plot_from_json(json_file):
    # 1. 检查文件是否存在
    if not os.path.exists(json_file):
        print(f"❌ Error: File not found: {json_file}")
        sys.exit(1)

    # 2. 读取 JSON 数据
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Failed to parse JSON: {e}")
        sys.exit(1)

    metadata = data.get('metadata', {})
    series_list = data.get('data_series', [])

    if not series_list:
        print("❌ Error: No 'data_series' found in JSON.")
        sys.exit(1)

    # 3. 初始化画布 (1行2列)
    setup_plot_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))

    # 准备线条样式循环器，方便区分不同曲线
    markers = cycle(['o', 's', '^', 'D', 'v', 'x'])
    linestyles = cycle(['-', '--', '-.', ':'])
    colors = cycle(['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00'])

    print(f"Processing {len(series_list)} data series...")

    # 4. 遍历数据并绘图
    for series in series_list:
        # 获取绘图数据
        try:
            x_data = series['flow_size_buckets_bytes']
            avg_slowdown = series['avg_fct_slowdown']
            p99_slowdown = series['p99_fct_slowdown']
        except KeyError as e:
            print(f"⚠️ Warning: Skipping a series due to missing key: {e}")
            continue

        # 生成图例标签 (Label)
        # 组合 Recovery, Timeout Mode 等关键信息
        rm = series.get('recovery_mechanism', 'Unknown')
        tm = series.get('timeout_mode', 'N/A')
        cc = series.get('congestion_control_mode', '')
        label = f"{rm} (TM={tm})"

        # 获取样式
        marker = next(markers)
        linestyle = next(linestyles)
        color = next(colors)

        # 绘制左图：平均值
        ax1.plot(x_data, avg_slowdown,
                 label=label,
                 marker=marker, linestyle=linestyle, color=color, alpha=0.8)

        # 绘制右图：P99
        ax2.plot(x_data, p99_slowdown,
                 label=label,
                 marker=marker, linestyle=linestyle, color=color, alpha=0.8)

    # 5. 设置图表细节

    # 标题信息
    topo = metadata.get('topology', 'Unknown Topo')
    load = metadata.get('network_load', 'N/A')
    fc = metadata.get('flow_control', 'N/A')
    main_title = f"FCT Slowdown Analysis\nTopo: {topo} | Load: {load}% | FC: {fc}"
    fig.suptitle(main_title, fontsize=16, y=0.98)

    # 左图配置
    ax1.set_title("Average FCT Slowdown vs. Flow Size")
    ax1.set_xlabel("Flow Size (Bytes) - Log Scale")
    ax1.set_ylabel("Avg Slowdown")
    ax1.set_xscale('log') # 关键：对数坐标
    ax1.grid(True, which="both", ls="-", alpha=0.4)
    ax1.legend()

    # 右图配置
    ax2.set_title("99th Percentile FCT Slowdown vs. Flow Size")
    ax2.set_xlabel("Flow Size (Bytes) - Log Scale")
    ax2.set_ylabel("P99 Slowdown")
    ax2.set_xscale('log') # 关键：对数坐标
    ax2.grid(True, which="both", ls="-", alpha=0.4)
    ax2.legend()

    # 6. 保存文件
    # 根据输入文件名自动生成输出文件名 (e.g., test.json -> test_plot.png)
    base_name = os.path.splitext(os.path.basename(json_file))[0]
    output_filename = f"{base_name}_plot.png"

    plt.tight_layout()
    plt.savefig(output_filename, dpi=300)
    print(f"\n✅ Plot saved successfully to: {output_filename}")

    # 如果是在本地桌面环境运行，取消下面的注释可以弹窗显示
    # plt.show()
    plt.close(fig)

def main():
    parser = argparse.ArgumentParser(description='Plot FCT Slowdown from JSON data.')
    parser.add_argument('json_file', type=str, help='Path to the input JSON file.')
    args = parser.parse_args()

    plot_from_json(args.json_file)

if __name__ == "__main__":
    main()
