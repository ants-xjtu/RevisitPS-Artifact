import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob

# 匯入專案提供的繪圖函式庫
import lib.py.plot.plot as plot

FONT_FAMILY = "DejaVu Sans"

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

def format_legend_label(label):
    normalized = str(label).lower()
    if "rps" in normalized:
        return "RPS"
    if "ecmp" in normalized:
        return "ECMP"
    if "bigsw" in normalized or "bigswitch" in normalized:
        return "BigSwitch"
    return str(label)

def sort_series_for_legend(series):
    order = {"ECMP": 0, "RPS": 1, "BigSwitch": 2}
    label = format_legend_label(series.get('load_balancing_mode', 'N/A'))
    return order.get(label, len(order))

def get_visible_xticks(x_tick_positions, x_tick_labels):
    visible_indices = [i for i in range(len(x_tick_labels))
                       if i % 2 == 0 or i == len(x_tick_labels) - 1]
    visible_positions = [x_tick_positions[i] for i in visible_indices]
    visible_labels = [format_bytes(x_tick_labels[i]) for i in visible_indices]
    return visible_positions, visible_labels

def set_plot_aspect(fig):
    fig.set_size_inches(9.6, 6)

def set_black_text_and_frame(ax):
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

def place_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    order = {"ECMP": 0, "RPS": 1, "BigSwitch": 2}
    sorted_items = sorted(zip(handles, labels), key=lambda item: order.get(item[1], len(order)))
    sorted_handles = [item[0] for item in sorted_items]
    sorted_labels = [item[1] for item in sorted_items]
    ax.legend(
        sorted_handles,
        sorted_labels,
        fontsize=25,
        prop={"family": FONT_FAMILY, "size": 25},
        loc="best",
        ncol=1,
        frameon=True,
        edgecolor="dimgray",
        facecolor="white",
        framealpha=1.0,
        borderaxespad=0.5,
        handlelength=1.4,
        handletextpad=0.35,
    )

def draw_normalized_plot(json_path, output_dir):
    with open(json_path, 'r') as f:
        data = json.load(f)

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"在文件 {json_path} 中找不到有效的 'data_series'。")
        return

    x_tick_labels = data_series_list[0]["flow_size_buckets_bytes"]
    x_tick_positions = np.arange(len(x_tick_labels))

    # 1️⃣ Normalized Avg
    p_avg = plot.LinePointPlot()
    set_plot_aspect(p_avg.fig)
    for series in data_series_list:
        y_avg = series["avg_fct_normalized"]
        if len(y_avg) != len(x_tick_positions):
            print(f"⚠️ Warning: avg point count mismatch for {series.get('load_balancing_mode','N/A')}; skipping.")
            continue
        label = format_legend_label(series.get('load_balancing_mode', 'N/A'))
        p_avg.plot(x_tick_positions, y_avg, label=label, markevery=1)

    p_avg.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
    p_avg.ax.set_ylabel("Normalized Avg FCT", fontsize=35)
    p_avg.ax.set_yscale("linear")
    p_avg.ax.set_ylim(0.9, 1.95)

    visible_xticks, visible_xtick_labels = get_visible_xticks(x_tick_positions, x_tick_labels)
    p_avg.ax.set_xticks(visible_xticks)
    p_avg.ax.set_xticklabels(
        visible_xtick_labels, rotation=45, ha='center', fontsize=26,
        fontfamily=FONT_FAMILY,
        rotation_mode='anchor'
    )
    p_avg.ax.set_xticks(x_tick_positions, minor=True)
    p_avg.ax.set_xlim(x_tick_positions[0] - 0.5, x_tick_positions[-1] + 0.5)
    p_avg.ax.tick_params(axis='x', which='major', direction='out', length=8, pad=10)
    p_avg.ax.tick_params(axis='x', which='minor', direction='out', length=4, labelbottom=False)
    p_avg.ax.tick_params(axis='y', labelsize=30)
    place_legend(p_avg.ax)
    set_black_text_and_frame(p_avg.ax)

    base_name = os.path.splitext(os.path.basename(json_path))[0]
    output_path_avg = os.path.join(output_dir, f"{base_name}_avg_normalized.pdf")
    plt.savefig(output_path_avg, bbox_inches="tight")
    plt.close()
    print(f"✅ Normalized Avg 圖已保存: {output_path_avg}")

    # 2️⃣ Normalized P99
    p_p99 = plot.LinePointPlot()
    set_plot_aspect(p_p99.fig)
    for series in data_series_list:
        y_p99 = series["p99_fct_normalized"]
        if len(y_p99) != len(x_tick_positions):
            print(f"⚠️ Warning: p99 point count mismatch for {series.get('load_balancing_mode','N/A')}; skipping.")
            continue
        label = format_legend_label(series.get('load_balancing_mode', 'N/A'))
        p_p99.plot(x_tick_positions, y_p99, label=label, markevery=1)

    p_p99.ax.set_xlabel("Flow Size (Bytes)", fontsize=35)
    p_p99.ax.set_ylabel("Normalized P99 FCT", fontsize=35)
    p_p99.ax.set_yscale("linear")
    p_p99.ax.set_xticks(visible_xticks)
    p_p99.ax.set_xticklabels(
        visible_xtick_labels, rotation=45, ha='center', fontsize=26,
        fontfamily=FONT_FAMILY,
        rotation_mode='anchor'
    )
    p_p99.ax.set_xticks(x_tick_positions, minor=True)
    p_p99.ax.set_xlim(x_tick_positions[0] - 0.5, x_tick_positions[-1] + 0.5)
    p_p99.ax.tick_params(axis='x', which='major', direction='out', length=8, pad=10)
    p_p99.ax.tick_params(axis='x', which='minor', direction='out', length=4, labelbottom=False)
    p_p99.ax.tick_params(axis='y', labelsize=30)
    place_legend(p_p99.ax)
    set_black_text_and_frame(p_p99.ax)
    p_p99.ax.set_ylim(0.85, 1.85)

    output_path_p99 = os.path.join(output_dir, f"{base_name}_p99_normalized.pdf")
    plt.savefig(output_path_p99, bbox_inches="tight")
    plt.close()
    print(f"✅ Normalized P99 圖已保存: {output_path_p99}")


def main():
    parser = argparse.ArgumentParser(
        description="從 JSON 檔案或目錄繪製 Normalized FCT 圖表"
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
        draw_normalized_plot(json_file, output_dir)

    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, '*.json'))
        if not json_files:
            print(f"⚠️ 在目錄 {args.input_path} 中沒有找到任何 .json 檔案。")
            return
        print(f"找到 {len(json_files)} 個 JSON 檔案，開始處理...")
        for json_file in json_files:
            output_dir = args.input_path
            print(f"--- 正在處理 {json_file} ---")
            draw_normalized_plot(json_file, output_dir)
        print("✅ 所有檔案處理完畢！")

    else:
        print(f"錯誤: {args.input_path} 不是有效的檔案或目錄。")
        return

if __name__ == '__main__':
    main()
