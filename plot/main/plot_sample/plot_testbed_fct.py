import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob

# 匯入專案提供的繪圖函式庫
import lib.py.plot.plot as plot

# 定义基础算法的颜色映射
BASE_COLORS = {
    'ecmp': '#1f77b4',      # 蓝色
    'rps': '#ff7f0e',       # 橙色
    'rsp': '#ff7f0e',       # 橙色 (rsp 和 RPS 相同)
    'bigswitch': '#2ca02c', # 绿色
    'drill': '#d62728',     # 红色
    'conga': '#9467bd',     # 紫色
    'letflow': '#8c564b',   # 棕色
    'conweave': '#e377c2',  # 粉色
}


def parse_algorithm_info(load_balancing_mode):
    """
    解析算法名称，返回 (基础算法名, 是否为simulation)
    例如: "ECMP-simulation" -> ("ecmp", True)
          "ecmp" -> ("ecmp", False)
    """
    mode_lower = load_balancing_mode.lower()
    is_simulation = '-simulation' in mode_lower
    base_algo = mode_lower.replace('-simulation', '').strip()
    return base_algo, is_simulation


def get_color_and_linestyle(load_balancing_mode):
    """
    根据算法名称返回颜色和线型
    simulation: 虚线 (dashed)
    testbed: 实线 (solid)
    """
    base_algo, is_simulation = parse_algorithm_info(load_balancing_mode)

    # 获取颜色，如果找不到则使用默认颜色
    color = BASE_COLORS.get(base_algo, None)

    # simulation 用虚线，testbed 用实线
    linestyle = '--' if is_simulation else '-'

    return color, linestyle


def format_bytes(num):
    if num is None:
        return ""
    num = float(num)
    if num < 1000:
        return f"{num / 1000:.1f}K"
    elif num < 10000:
        return f"{num / 1000:.1f}K"
    elif num < 1000000:
        return f"{num / 1000:.0f}K"
    else:
        return f"{num / 1000000:.1f}M"


def draw_slowdown_plot(json_path, output_dir):
    with open(json_path, 'r') as f:
        data = json.load(f)

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"在文件 {json_path} 中找不到有效的 'data_series'。")
        return

    x_tick_labels = data_series_list[0]["flow_size_buckets_bytes"]
    x_tick_positions = range(len(x_tick_labels))

    # 1️⃣ Avg Slowdown
    p_avg = plot.LinePointPlot()
    for series in data_series_list:
        y_avg = series["avg_fct_slowdown"]
        lb_mode = series.get('load_balancing_mode', 'N/A')
        base_algo, is_simulation = parse_algorithm_info(lb_mode)

        # 生成标签（不显示 recovery_mechanism 如果是 N/A）
        recovery = series.get('recovery_mechanism', 'N/A')
        if recovery == 'N/A':
            label = f"{lb_mode}"
        else:
            label = f"{lb_mode}({recovery})"

        # 获取颜色和线型
        color, linestyle = get_color_and_linestyle(lb_mode)

        num_points = len(y_avg)
        mark_every_indices = list(range(0, num_points, 2))
        if num_points - 1 not in mark_every_indices:
            mark_every_indices.append(num_points - 1)

        # 绘制时指定颜色和线型
        if color:
            p_avg.plot(x_tick_positions, y_avg, label=label, markevery=mark_every_indices,
                      color=color, linestyle=linestyle)
        else:
            p_avg.plot(x_tick_positions, y_avg, label=label, markevery=mark_every_indices,
                      linestyle=linestyle)

    p_avg.ax.set_xlabel("Flow Size (Bytes)")
    p_avg.ax.set_ylabel("Avg Slowdown")
    p_avg.ax.set_yscale("linear")

    xtick_labels_shown = [
        format_bytes(x) if i % 2 == 0 or i == len(x_tick_labels) - 1 else ""
        for i, x in enumerate(x_tick_labels)
    ]
    p_avg.ax.set_xticks(x_tick_positions)
    p_avg.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=20)
    p_avg.ax.tick_params(axis='y', labelsize=20)
    p_avg.ax.legend(fontsize=20)

    base_name = os.path.splitext(os.path.basename(json_path))[0]
    output_path_avg = os.path.join(output_dir, f"{base_name}_avg_slowdown.pdf")
    plt.savefig(output_path_avg)
    plt.close()
    print(f"✅ Avg Slowdown 圖已保存: {output_path_avg}")

    # 2️⃣ P99 Slowdown
    p_p99 = plot.LinePointPlot()
    for series in data_series_list:
        y_p99 = series["p99_fct_slowdown"]
        lb_mode = series.get('load_balancing_mode', 'N/A')
        base_algo, is_simulation = parse_algorithm_info(lb_mode)

        # 生成标签（不显示 recovery_mechanism 如果是 N/A）
        recovery = series.get('recovery_mechanism', 'N/A')
        if recovery == 'N/A':
            label = f"{lb_mode}"
        else:
            label = f"{lb_mode}({recovery})"

        # 获取颜色和线型
        color, linestyle = get_color_and_linestyle(lb_mode)

        num_points = len(y_p99)
        mark_every_indices = list(range(0, num_points, 2))
        if num_points - 1 not in mark_every_indices:
            mark_every_indices.append(num_points - 1)

        # 绘制时指定颜色和线型
        if color:
            p_p99.plot(x_tick_positions, y_p99, label=label, markevery=mark_every_indices,
                      color=color, linestyle=linestyle)
        else:
            p_p99.plot(x_tick_positions, y_p99, label=label, markevery=mark_every_indices,
                      linestyle=linestyle)

    p_p99.ax.set_xlabel("Flow Size (Bytes)")
    p_p99.ax.set_ylabel("P99 Slowdown")
    p_p99.ax.set_yscale("linear")
    p_p99.ax.set_xticks(x_tick_positions)
    p_p99.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=20)
    p_p99.ax.tick_params(axis='y', labelsize=20)
    p_p99.ax.legend(fontsize=20)

    output_path_p99 = os.path.join(output_dir, f"{base_name}_p99_slowdown.pdf")
    plt.savefig(output_path_p99)
    plt.close()
    print(f"✅ P99 Slowdown 圖已保存: {output_path_p99}")


def main():
    parser = argparse.ArgumentParser(
        description="從 JSON 檔案或目錄繪製 Slowdown 圖表"
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="輸入路徑，可以是單個 JSON 檔案或包含多個 JSON 檔案的目錄。"
    )
    args = parser.parse_args()

    if os.path.isfile(args.input_path):
        json_file = args.input_path
        output_dir = os.path.dirname(json_file)
        print(f"--- 正在處理 {json_file} ---")
        draw_slowdown_plot(json_file, output_dir)

    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ 在目錄 {args.input_path} 中沒有找到任何 .json 檔案。")
            return
        print(f"找到 {len(json_files)} 個 JSON 檔案，開始處理...")
        for json_file in json_files:
            output_dir = args.input_path
            print(f"--- 正在處理 {json_file} ---")
            draw_slowdown_plot(json_file, output_dir)
        print("✅ 所有檔案處理完畢！")

    else:
        print(f"錯誤: {args.input_path} 不是有效的檔案或目錄。")
        return


if __name__ == '__main__':
    main()
