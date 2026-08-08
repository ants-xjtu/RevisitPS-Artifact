import argparse
import json
import matplotlib.pyplot as plt
from matplotlib.ticker import LogFormatter
import numpy as np
import os
import glob
from collections import defaultdict
import re
import math

# 匯入專案提供的繪圖函式庫
import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"

# ==============================================================================
# 變更開始 (1/3): 新增自訂錯誤率順序列表
# 您可以在此處定義圖例和繪圖的順序
# ==============================================================================
DESIRED_ERROR_RATE_ORDER = [
    '0.0',
    '0.001',  # 等同於 1e-3
    '0.0001', # 等同於 1e-4
    '1e-05',
    '1e-06',
    '1e-07',
]
# ==============================================================================

def format_bytes(num):
    """
    根据特定规则将字节数格式化为易读的 K, M 格式。
    """
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

# ==============================================================================
# 變更開始 (2/3): 新增一個函式來標準化圖例標籤
# ==============================================================================
def format_error_rate_label(error_rate_str):
    """將錯誤率字串格式化為標準的圖例標籤 (使用 LaTeX)"""
    if error_rate_str is None:
        return "BER: N/A"
    try:
        val = float(error_rate_str)
        if val == 0.0:
            return "BER: 0.0"
        else:
            # 計算 10 的次方
            exponent = math.floor(math.log10(val))
            # 格式化為 LaTeX 字串
            return f"BER: $10^{{{exponent}}}$"
    except (ValueError, TypeError):
        # 如果無法轉換為數字，則返回原字串
            return f"BER: {error_rate_str}"
# ==============================================================================


def apply_plot_style(fig, ax, legend):
    fig.set_size_inches(9.6, 6)
    ax.set_title("")
    ax.xaxis.label.set_fontfamily(FONT_FAMILY)
    ax.xaxis.label.set_color("black")
    ax.xaxis.label.set_size(35)
    ax.yaxis.label.set_fontfamily(FONT_FAMILY)
    ax.yaxis.label.set_color("black")
    ax.yaxis.label.set_size(35)
    ax.tick_params(axis="both", which="both", colors="black", labelsize=30)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(FONT_FAMILY)
        label.set_color("black")
    for spine in ax.spines.values():
        spine.set_color("black")
    if legend is not None:
        legend.get_frame().set_edgecolor("dimgray")
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_alpha(1.0)
        for txt in legend.get_texts():
            txt.set_fontfamily(FONT_FAMILY)
            txt.set_color("black")
            txt.set_fontsize(25)
        title = legend.get_title()
        if title is not None:
            title.set_fontfamily(FONT_FAMILY)
            title.set_color("black")


def create_compact_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    ncol = max(1, math.ceil(len(labels) / 2))
    return ax.legend(
        handles,
        labels,
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=ncol,
        frameon=False,
        borderaxespad=0.2,
        borderpad=0.2,
        columnspacing=0.4,
        handletextpad=0.2,
        labelspacing=0.15,
        handlelength=1.0,
    )


def draw_error_rate_fct_plot(json_path, output_dir):
    """
    从单个 JSON 文件为每种 LB/Recovery 组合绘制 FCT 对比图，
    图中每条线代表不同的 Error Rate。
    """
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"在文件 {json_path} 中找不到有效的 'data_series'。")
        return

    # 1️⃣ 将数据按 (LB Mode, Recovery Mechanism) 分组
    grouped_series = defaultdict(list)
    for series in data_series_list:
        group_key = f"{series.get('load_balancing_mode', 'N/A')}({series.get('recovery_mechanism', 'N/A')})"
        grouped_series[group_key].append(series)

    base_name = os.path.splitext(os.path.basename(json_path))[0]
    
    # 2️⃣ 为每个分组绘制 Avg 和 p99 FCT 图
    for group_label, series_list in grouped_series.items():
        print(f"  -> 正在為 '{group_label}' 繪圖...")

        # ==============================================================================
        # 變更開始 (3/3): 根據 DESIRED_ERROR_RATE_ORDER 排序數據系列
        # ==============================================================================
        series_map = {s.get('error_rate'): s for s in series_list}
        ordered_series_to_plot = []
        for err_rate in DESIRED_ERROR_RATE_ORDER:
            if err_rate in series_map:
                ordered_series_to_plot.append(series_map[err_rate])
            else:
                # 如果在數據中找不到定義的錯誤率，印出警告
                print(f"    ⚠️  警告: 在 '{group_label}' 分組中找不到錯誤率 '{err_rate}' 的數據。")
        # ==============================================================================

        if not ordered_series_to_plot:
            print(f"    ❌ 錯誤: 根據指定的順序，在 '{group_label}' 分組中找不到任何可繪製的數據。")
            continue

        x_tick_labels = ordered_series_to_plot[0]["flow_size_buckets_bytes"]
        x_tick_positions = range(len(x_tick_labels))

        # 绘 avg FCT
        p_avg = plot.LinePointPlot()
        for series in ordered_series_to_plot: # <--- 使用排序後的新列表
            y_avg = series["avg_fct_slowdown"]
            # 使用新的格式化函式來建立標籤
            label = format_error_rate_label(series.get('error_rate'))
            num_points = len(y_avg)
            mark_every_indices = list(range(0, num_points, 2))
            if num_points-1 not in mark_every_indices:
                mark_every_indices.append(num_points-1)
            p_avg.plot(x_tick_positions, y_avg, label=label, markevery=mark_every_indices)

        p_avg.ax.set_xlabel("Flow Size (Bytes)")
        p_avg.ax.set_ylabel("Average FCT Slowdown")
        gamma = 0.001
        p_avg.ax.set_yscale("function", functions=(lambda x: np.power(x, gamma), lambda y: np.power(y, 1/gamma)))
        
        xtick_labels_shown = [format_bytes(x) if i % 2 == 0 or i == len(x_tick_labels)-1 else "" for i, x in enumerate(x_tick_labels)]
        p_avg.ax.set_xticks(x_tick_positions)
        p_avg.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center')
        legend = create_compact_legend(p_avg.ax)
        legend.set_zorder(100)
        apply_plot_style(p_avg.fig, p_avg.ax, legend)

        safe_group_label = re.sub(r'[^\w\-_.]', '_', group_label)
        output_path_avg = os.path.join(output_dir, f"{base_name}_{safe_group_label}_avg.pdf")
        plt.savefig(output_path_avg, bbox_inches="tight")
        plt.close()
        print(f"    ✅ avg 圖已保存: {output_path_avg}")

        # 绘 p99 FCT
        p_p99 = plot.LinePointPlot()
        for series in ordered_series_to_plot: # <--- 使用排序後的新列表
            y_p99 = series["p99_fct_slowdown"]
            # 使用新的格式化函式來建立標籤
            label = format_error_rate_label(series.get('error_rate'))
            num_points = len(y_p99)
            mark_every_indices = list(range(0, num_points, 2))
            if num_points-1 not in mark_every_indices:
                mark_every_indices.append(num_points-1)
            p_p99.plot(x_tick_positions, y_p99, label=label, markevery=mark_every_indices)

        p_p99.ax.set_xlabel("Flow Size (Bytes)")
        p_p99.ax.set_ylabel("P99 FCT Slowdown")
        p_p99.ax.set_yscale("function", functions=(lambda x: np.power(x, gamma), lambda y: np.power(y, 1/gamma)))
        p_p99.ax.set_xticks(x_tick_positions)
        p_p99.ax.set_xticklabels(xtick_labels_shown, rotation=45, ha='center')
        legend = create_compact_legend(p_p99.ax)
        legend.set_zorder(100)
        apply_plot_style(p_p99.fig, p_p99.ax, legend)
        
        output_path_p99 = os.path.join(output_dir, f"{base_name}_{safe_group_label}_p99.pdf")
        plt.savefig(output_path_p99, bbox_inches="tight")
        plt.close()
        print(f"    ✅ p99 圖已保存: {output_path_p99}")


def main():
    parser = argparse.ArgumentParser(
        description="從 JSON 檔案或目錄繪製 Error Rate vs FCT 的對比圖表。"
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
        print(f"--- 正在處理檔案: {json_file} ---")
        draw_error_rate_fct_plot(json_file, output_dir)

    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ 在目錄 {args.input_path} 中沒有找到任何 .json 檔案。")
            return
        print(f"找到 {len(json_files)} 個 JSON 檔案，開始處理...")
        for json_file in json_files:
            output_dir = args.input_path
            print(f"--- 正在處理檔案: {json_file} ---")
            draw_error_rate_fct_plot(json_file, output_dir)
        print("✅ 所有檔案處理完畢！")

    else:
        print(f"錯誤: {args.input_path} 不是有效的檔案或目錄。")
        return

if __name__ == '__main__':
    main()
