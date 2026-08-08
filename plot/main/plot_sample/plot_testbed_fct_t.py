import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob

# 專案提供的繪圖函式庫
import lib.py.plot.plot as plot

def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num/1000:.1f}K"
    elif num < 10000:
        return f"{num/1000:.1f}K"
    elif num < 1000000:
        return f"{num/1000:.0f}K"
    else:
        return f"{num/1000000:.1f}M"

def draw_real_fct_plot(json_path, output_dir):
    with open(json_path, 'r') as f:
        data = json.load(f)

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"在文件 {json_path} 中找不到有效的 'data_series'。")
        return

    x_tick_labels = data_series_list[0]["flow_size_buckets_bytes"]
    x_tick_positions = range(len(x_tick_labels))

    # 绘 avg FCT
    p_avg = plot.LinePointPlot()
    for series in data_series_list:
        y_avg = series["avg_fct"]
        label = f"{series.get('load_balancing_mode','N/A')}({series.get('recovery_mechanism','N/A')})"
        num_points = len(y_avg)
        mark_every_indices = list(range(0, num_points, 2))
        if num_points-1 not in mark_every_indices:
            mark_every_indices.append(num_points-1)
        p_avg.plot(x_tick_positions, y_avg, label=label, markevery=mark_every_indices)

    p_avg.ax.set_xlabel("Flow Size (Bytes)")
    p_avg.ax.set_ylabel("Average FCT")

    xtick_labels_shown = [format_bytes(x) if i % 2 == 0 or i == len(x_tick_labels)-1 else "" for i, x in enumerate(x_tick_labels)]
    p_avg.ax.set_xticks(x_tick_positions)
    p_avg.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=14)
    p_avg.ax.tick_params(axis='y', labelsize=14)
    p_avg.ax.legend(fontsize=14)

    base_name = os.path.splitext(os.path.basename(json_path))[0]
    output_path_avg = os.path.join(output_dir, f"{base_name}_avgFCT.pdf")
    plt.savefig(output_path_avg)
    plt.close()
    print(f"✅ avg FCT 图已保存: {output_path_avg}")

    # 绘 p99 FCT
    p_p99 = plot.LinePointPlot()
    for series in data_series_list:
        y_p99 = series["p99_fct"]
        label = f"{series.get('load_balancing_mode','N/A')}({series.get('recovery_mechanism','N/A')})"
        num_points = len(y_p99)
        mark_every_indices = list(range(0, num_points, 2))
        if num_points-1 not in mark_every_indices:
            mark_every_indices.append(num_points-1)
        p_p99.plot(x_tick_positions, y_p99, label=label, markevery=mark_every_indices)

    p_p99.ax.set_xlabel("Flow Size (Bytes)")
    p_p99.ax.set_ylabel("P99 FCT")
    p_p99.ax.set_xticks(x_tick_positions)
    p_p99.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=14)
    p_p99.ax.tick_params(axis='y', labelsize=14)
    p_p99.ax.legend(fontsize=14)

    output_path_p99 = os.path.join(output_dir, f"{base_name}_p99FCT.pdf")
    plt.savefig(output_path_p99)
    plt.close()
    print(f"✅ p99 FCT 图已保存: {output_path_p99}")


def main():
    parser = argparse.ArgumentParser(description="从 JSON 文件或目录绘制真实 FCT 图")
    parser.add_argument("input_path", type=str, help="输入 JSON 文件或包含 JSON 文件的目录")
    args = parser.parse_args()

    if os.path.isfile(args.input_path):
        output_dir = os.path.dirname(args.input_path)
        draw_real_fct_plot(args.input_path, output_dir)
    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ 目录 {args.input_path} 中没有找到任何 JSON 文件")
            return
        for json_file in json_files:
            draw_real_fct_plot(json_file, args.input_path)
    else:
        print(f"❌ 错误: {args.input_path} 不是有效的文件或目录")

if __name__ == '__main__':
    main()