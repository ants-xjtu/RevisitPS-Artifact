#!/usr/bin/python3

import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
import csv # 导入CSV模块

FONT_FAMILY = "DejaVu Sans"
PAPER_SERIES_ORDER = ["RPS", "DRILL", "AR"]

# 确保可以导入项目提供的绘图函式库
try:
    import lib.py.plot.plot as plot
except ImportError:
    print("错误: 无法导入 'lib.py.plot.plot'。请确保该文件存在且路径正确。")
    exit(1)

# --- 辅助函数 ---

def order_data_series(data_series_list):
    order = {name: index for index, name in enumerate(PAPER_SERIES_ORDER)}
    return sorted(
        data_series_list,
        key=lambda series: order.get(
            series.get("load_balancing_mode"), len(PAPER_SERIES_ORDER)
        ),
    )

def get_percentile_from_aggregated(aggregated_data, percentile):
    """
    从聚合的 [value, count] 数据中计算指定的百分位数。
    """
    if not aggregated_data:
        return None
    total_count = sum(item[1] for item in aggregated_data)
    if total_count == 0:
        return None
    target_count = total_count * (percentile / 100.0)
    cumulative_count = 0
    for value, count in aggregated_data:
        cumulative_count += count
        if cumulative_count >= target_count:
            return value
    return aggregated_data[-1][0]

def calculate_cdf_from_aggregated(data):
    """
    从聚合的 [value, count] 数据计算 CDF。
    """
    if not data:
        return [], []
    data.sort(key=lambda x: x[0])
    values = [item[0] for item in data]
    counts = [item[1] for item in data]
    total_count = sum(counts)
    if total_count == 0:
        return [], []
    cumulative_counts = np.cumsum(counts)
    cdf_probs = cumulative_counts / total_count
    return values, list(cdf_probs)


def include_zero_distance_packets(data, ooo_packet_rate):
    data_with_zero = [list(item) for item in data]
    if not data_with_zero:
        return data_with_zero

    has_zero = any(item[0] == 0 for item in data_with_zero)
    if has_zero:
        return data_with_zero

    rate = ooo_packet_rate
    if rate > 1:
        rate /= 100
    if rate <= 0:
        return data_with_zero

    ooo_count = sum(item[1] for item in data_with_zero)
    total_count = ooo_count / rate
    zero_count = max(0, int(round(total_count - ooo_count)))
    return [[0, zero_count]] + data_with_zero


def set_black_text_ticks_and_frame(ax):
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.tick_params(axis='both', which='both', colors="black")
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color("black")
        label.set_fontfamily(FONT_FAMILY)
    for spine in ax.spines.values():
        spine.set_color("black")


# --- 数据输出函数 ---

def output_table_data(json_data, output_path):
    """将关键统计数据输出到 CSV 文件中"""
    data_series_list = order_data_series(json_data.get("data_series", []))
    if not data_series_list:
        return
    header = [
        "Load Balancing", "Recovery Mechanism", "OOO Rate (%)",
        "Dist Median (p50)", "Dist p90", "Dist p99", "Dist p99.9", "Dist Max"
    ]
    rows = []
    for series in data_series_list:
        dist_data = series.get("reordering_distance_packets", [])
        if dist_data:
            p50 = get_percentile_from_aggregated(dist_data, 50)
            p90 = get_percentile_from_aggregated(dist_data, 90)
            p99 = get_percentile_from_aggregated(dist_data, 99)
            p99_9 = get_percentile_from_aggregated(dist_data, 99.9)
            max_val = dist_data[-1][0]
        else:
            p50, p90, p99, p99_9, max_val = ('N/A',) * 5
        row = [
            series.get('load_balancing_mode', 'N/A'),
            series.get('recovery_mechanism', 'N/A'),
            f"{series.get('ooo_packet_rate', 0) * 100:.4f}",
            p50, p90, p99, p99_9, max_val
        ]
        rows.append(row)
    try:
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"📊 表格数据已储存至: {output_path}")
    except IOError as e:
        print(f"错误: 无法写入CSV文件 {output_path}。错误: {e}")


# --- 绘图函数 ---

def draw_ooo_rate_plot(json_data, output_path):
    """从JSON数据绘制 OOO Packet Rate 柱状图 (使用 BarPlot 类)"""
    metadata = json_data.get("metadata", {})
    data_series_list = order_data_series(json_data.get("data_series", []))
    if not data_series_list:
        return
    labels = [f"{s.get('load_balancing_mode', 'N/A')}({s.get('recovery_mechanism', 'N/A')})" for s in data_series_list]
    rates = [s.get('ooo_packet_rate', 0) for s in data_series_list]
    p = plot.BarPlot()
    p.insert_yvals(rates, label='OOO Packet Rate')
    bar_containers = p.plot(xlabels=labels)
    if bar_containers:
        p.ax.bar_label(bar_containers[0], fmt='%.4f', padding=3, fontsize=10)
    p.ax.set_ylabel('Out-of-Order Packet Rate')
    plt.setp(p.ax.get_xticklabels(), rotation=30, ha="right", rotation_mode="anchor")
    if max(rates, default=0) > 0:
        p.ax.set_ylim(top=p.ax.get_ylim()[1] * 1.15)
    p.ax.legend()
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"✅ OOO Rate 柱状图 (分组样式) 已储存至: {output_path}")

def draw_reorder_distance_cdf_plot(json_data, output_path):
    """从JSON数据绘制优化后的 Reordering Distance CDF 图"""
    metadata = json_data.get("metadata", {})
    data_series_list = order_data_series(json_data.get("data_series", []))
    if not data_series_list:
        return

    p = plot.CDFPlot()
    p.fig.set_size_inches(9.6, 6)
    plotted_something = False

    # 提取公共的恢复机制，用于图表标题
    # 这里我们假设所有数据序列的恢复机制都是相同的
    common_recovery_mechanism = ""
    if data_series_list:
        common_recovery_mechanism = data_series_list[0].get('recovery_mechanism', 'N/A')

    for series in data_series_list:
        dist_data = series.get("reordering_distance_packets", [])
        if not dist_data:
            continue

        dist_data = include_zero_distance_packets(dist_data, series.get('ooo_packet_rate', 0))
        x_dist, y_cdf = calculate_cdf_from_aggregated(dist_data)

        if x_dist:
            if x_dist[-1] < 130:
                x_dist = list(x_dist) + [130]
                y_cdf = list(y_cdf) + [y_cdf[-1]]
            mode = series.get('load_balancing_mode', 'N/A')

            p.plot(x_dist, cdf=y_cdf, label=mode, linewidth=6)
            plotted_something = True

    if not plotted_something:
        plt.close()
        return

    # --- 这里是绘图设置的优化 ---

    # 设置X/Y轴标签和范围 (与原来保持一致)
    p.ax.set_xlabel("Reorder Distance (Packets)", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    p.ax.set_ylabel("CDF", fontsize=35, fontfamily=FONT_FAMILY, color="black")
    p.ax.set_xscale("log")
    p.ax.set_xlim(0.9, 130)
    p.ax.set_xticks([1, 10, 100])
    p.ax.set_xticklabels(["1", "10", "100"])
    p.ax.set_ylim(0.45, 1.05)
    p.ax.set_yticks(np.arange(0.5, 1.01, 0.1))

    p.ax.tick_params(axis='both', which='major', labelsize=30)

    p.ax.legend(
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        loc="lower right",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
    )
    set_black_text_ticks_and_frame(p.ax)

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"✅ Reorder Distance CDF 图 (优化版) 已储存至: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="从 OOO JSON 数据文件或目录绘制图表并输出表格数据"
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="输入路径，可以是单个 JSON 檔案或包含多个 JSON 檔案的目录。"
    )
    args = parser.parse_args()

    if os.path.isfile(args.input_path):
        json_files = [args.input_path]
    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ 在目录 {args.input_path} 中没有找到任何 .json 檔案。")
            return
    else:
        print(f"错误: {args.input_path} 不是有效的檔案或目录。")
        return

    print(f"找到 {len(json_files)} 个 JSON 檔案，开始处理...")
    for json_file in json_files:
        print(f"--- 正在处理 {json_file} ---")
        try:
            with open(json_file, 'r') as f:
                json_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"错误: 无法读取或解析JSON文件 {json_file}。错误: {e}")
            continue

        series_all = json_data.get("data_series", [])
        filtered = []
        for s in series_all:
            lb = str(s.get("load_balancing_mode", ""))
            rec = str(s.get("recovery_mechanism", ""))
            if lb in ("SGLB", "ECMP", "ConWeave"):
                continue
            if rec.replace("_", "").lower() == "idealtrimming":
                continue
            if lb == "WAdapt":
                s = dict(s)
                s["load_balancing_mode"] = "SGLB"
            elif lb.lower() in ("drillgroup",):
                s = dict(s)
                s["load_balancing_mode"] = "DRILL"
            filtered.append(s)
        json_data["data_series"] = filtered

        base_name = os.path.splitext(os.path.basename(json_file))[0]
        output_dir = os.path.dirname(json_file)

        rate_plot_path = os.path.join(output_dir, f"{base_name}_rate.pdf")
        dist_plot_path = os.path.join(output_dir, f"{base_name}_dist_cdf.pdf")
        table_data_path = os.path.join(output_dir, f"{base_name}_table_data.csv")

        draw_ooo_rate_plot(json_data, rate_plot_path)
        draw_reorder_distance_cdf_plot(json_data, dist_plot_path)
        output_table_data(json_data, table_data_path)

    print("\n✅ 所有檔案处理完毕！")


if __name__ == '__main__':
    main()
