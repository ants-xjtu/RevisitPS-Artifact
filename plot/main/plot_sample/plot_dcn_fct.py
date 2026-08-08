import argparse
import json
import matplotlib.pyplot as plt
from matplotlib.ticker import LogFormatter
import numpy as np
import os
import glob
import sys

# 尝试导入你的绘图库，如果失败则跳过（方便调试）
try:
    import lib.py.plot.plot as plot
except ImportError:
    print("⚠️ Warning: Could not import lib.py.plot.plot. Plotting functions might fail.")
    pass

# ==============================================================================
# 1. 定义排序列表 (Desired Orders)
# ==============================================================================

desired_order_for_lossless = [
    "ECMP(NAK+GBN)",
    "ConWeave(NAK+GBN)",
    "DRILL(RTO+GBN)",
    "RPS(RTO+GBN)",
    "AR(RTO+GBN)",
]

desired_order_for_lossy = [
    "ECMP(NAK+SR)",
    "ConWeave(NAK+SR)",
    "DRILL(RTO+GBN)",
    "RPS(RTO+GBN)",
    "AR(RTO+GBN)",
    "AR(DCP)",
]

desired_order_for_incast = [
    "ECMP(NAK+SR)",
    "LetFlow(NAK+SR)",
    "CONGA(NAK+SR)",
    "ConWeave(NAK+SR)",
    "RPS(RTO+GBN)",
    "AR(RTO+GBN)",
]

# --- 新增: 针对 Three Layer 拓扑的排序 ---
desired_order_for_three_layer = [
    "WAR(RTO+GBN+slowstart)",
    "WAR(IdealTrimming)", # 如果有 IdealTrimming 也可以加在这里
    "WAR(IdealTrimming+slowstart)",
]
# ==============================================================================


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

def draw_fct_plot(json_path, output_dir):
    """从单个 JSON 文件绘制 avg 和 p99 两张 FCT 图"""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 无法读取 JSON 文件 {json_path}: {e}")
        return

    meta = data.get("metadata", {})
    topology = meta.get("topology", "") # 默认为空字符串防止报错
    network_load = int(meta.get("network_load", 0))
    flow_control = meta.get("flow_control")
    load_type = meta.get("load_type")

    # ==============================================================================
    # 2. 选择排序逻辑 (Selection Logic)
    # ==============================================================================
    desired_order = None

    if flow_control == "Lossless":
        desired_order = desired_order_for_lossless

    elif flow_control == "Lossy":
        # 默认使用 lossy
        desired_order = desired_order_for_lossy

        # --- 新增判断逻辑: 包含 "three_layer" ---
        if "Asym" in topology:
            print(f"ℹ️ 检测到 Three Layer 拓扑 ({topology})，使用专用排序列表。")
            desired_order = desired_order_for_three_layer

        # 既有逻辑: Incast 特殊场景
        elif load_type == "AliStorage2019" and topology in ["fat_k8_100G_OS1", "leaf_spine_L8_S16_100G_OS1"] and network_load == 80:
            print(f"ℹ️ 检测到 Incast 场景，使用 Incast 排序列表。")
            desired_order = desired_order_for_incast

    else:
        print(f"⚠️ 未知的配置组合，无法确定排序: FC={flow_control}, Topo={topology}")
        # 如果不知道用哪个，可以回退到默认或者直接返回
        # 这里我们尝试继续，看能不能画出东西，或者直接 return
        # return

    # ==============================================================================

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"⚠️ 文件 {os.path.basename(json_path)} 中没有 'data_series' 数据。")
        return

    # 筛选和排序数据
    series_to_plot = []
    if desired_order:
        for desired_label in desired_order:
            found_series = None
            for series in data_series_list:
                current_label = f"{series.get('load_balancing_mode','N/A')}({series.get('recovery_mechanism','N/A')})"
                if current_label == desired_label:
                    found_series = series
                    break
            if found_series:
                series_to_plot.append(found_series)
    else:
        # 如果没匹配到任何 order 规则，就画全部
        print("⚠️ 未匹配到特定 Order 规则，将绘制文件中所有 Series。")
        series_to_plot = data_series_list

    if not series_to_plot:
        print(f"❌ 错误: 在文件 {json_path} 中找不到符合 desired_order 的数据系列。")
        print(f"   当前使用的 Order 列表包含: {desired_order}")
        return

    x_tick_labels = data_series_list[0]["flow_size_buckets_bytes"]
    x_tick_positions = range(len(x_tick_labels))
    xtick_labels_shown = [format_bytes(x) if i % 2 == 0 or i == len(x_tick_labels)-1 else "" for i, x in enumerate(x_tick_labels)]

    gamma = 0.001

    # --- 1. 绘制 AVG 图 ---
    try:
        p_avg = plot.LinePointPlot()
        for series in series_to_plot:
            y_avg = series["avg_fct_slowdown"]
            label = f"{series.get('load_balancing_mode','N/A')}({series.get('recovery_mechanism','N/A')})"
            num_points = len(y_avg)
            mark_every = list(range(0, num_points, 2))
            if num_points-1 not in mark_every: mark_every.append(num_points-1)

            p_avg.plot(x_tick_positions, y_avg, label=label, markevery=mark_every)

        p_avg.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
        p_avg.ax.set_ylabel("Average FCT Slowdown", fontsize=34)
        p_avg.ax.set_yscale("function", functions=(lambda x: np.power(x, gamma), lambda y: np.power(y, 1/gamma)))
        p_avg.ax.set_xticks(x_tick_positions)
        p_avg.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=30)
        p_avg.ax.tick_params(axis='y', labelsize=30)
        legend = p_avg.ax.legend(fontsize=23)
        legend.set_zorder(100)

        base_name = os.path.splitext(os.path.basename(json_path))[0]
        output_path_avg = os.path.join(output_dir, f"{base_name}_avg.pdf")
        plt.savefig(output_path_avg, bbox_inches='tight')
        plt.close()
        print(f"✅ AVG saved: {output_path_avg}")
    except Exception as e:
        print(f"❌ 绘图 AVG 失败: {e}")

    # --- 2. 绘制 P99 图 ---
    try:
        p_p99 = plot.LinePointPlot()
        for series in series_to_plot:
            y_p99 = series["p99_fct_slowdown"]
            label = f"{series.get('load_balancing_mode','N/A')}({series.get('recovery_mechanism','N/A')})"
            num_points = len(y_p99)
            mark_every = list(range(0, num_points, 2))
            if num_points-1 not in mark_every: mark_every.append(num_points-1)

            p_p99.plot(x_tick_positions, y_p99, label=label, markevery=mark_every)

        p_p99.ax.set_xlabel("Flow Size (Bytes)", fontsize=40)
        p_p99.ax.set_ylabel("P99 FCT Slowdown", fontsize=34)
        p_p99.ax.set_yscale("function", functions=(lambda x: np.power(x, gamma), lambda y: np.power(y, 1/gamma)))
        p_p99.ax.set_xticks(x_tick_positions)
        p_p99.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center', fontsize=30)
        p_p99.ax.tick_params(axis='y', labelsize=30)
        legend = p_p99.ax.legend(fontsize=23)
        legend.set_zorder(100)

        output_path_p99 = os.path.join(output_dir, f"{base_name}_p99.pdf")
        plt.savefig(output_path_p99, bbox_inches='tight')
        plt.close()
        print(f"✅ P99 saved: {output_path_p99}")
    except Exception as e:
        print(f"❌ 绘图 P99 失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="从 JSON 檔案或目錄繪製 FCT 圖表")
    parser.add_argument("input_path", type=str, help="輸入路徑 (JSON 檔案或目錄)")
    args = parser.parse_args()

    # 清理路径字符串 (去除首尾空格)
    raw_path = args.input_path.strip()
    input_path = os.path.abspath(os.path.expanduser(raw_path))

    print(f"Processing Path: {input_path}")

    if os.path.isfile(input_path):
        json_file = input_path
        output_dir = os.path.dirname(json_file)
        print(f"--- 正在处理单文件: {os.path.basename(json_file)} ---")
        draw_fct_plot(json_file, output_dir)

    elif os.path.isdir(input_path):
        json_files = glob.glob(os.path.join(input_path, '*.json'))
        if not json_files:
            print(f"⚠️  在目录 {input_path} 中未找到 .json 文件。")
            return

        print(f"📂 找到 {len(json_files)} 个文件，开始批量处理...")
        for json_file in json_files:
            output_dir = input_path
            print(f"--- 正在处理: {os.path.basename(json_file)} ---")
            draw_fct_plot(json_file, output_dir)
        print("✅ 所有文件处理完毕。")

    else:
        print("\n❌ 错误: 路径不存在或不是有效的文件/目录。")
        print(f"   输入路径: {raw_path}")

        if "DATA_TOPO_three_layer_DATA_TOPO_three_layer" in raw_path:
            print("\n💡 提示: 我检测到文件名中出现了重复前缀 'DATA_TOPO_three_layer_'。")
            print("   请检查命令行参数，去掉重复的部分再试一次。")

if __name__ == '__main__':
    main()