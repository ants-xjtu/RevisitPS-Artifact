#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from matplotlib.ticker import ScalarFormatter
from collections import defaultdict

# 导入项目提供的绘图函数库
import lib.py.plot.plot as plot

def draw_workload_comparison(json_path, output_dir=None):
    """
    从 JSON 文件绘制不同 workload 的 CDF 对比图，并对 workload 名称进行自定义映射
    """
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {json_path}")
        return
    except json.JSONDecodeError:
        print(f"❌ 错误: 无法解析 JSON 文件 {json_path}")
        return

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"⚠️ 在文件 {json_path} 中没有找到有效的 'data_series'。")
        return

    lb_mode_filter = "AR"
    recovery_filter = "RTO+GBN"

    # 按 workload 收集数据
    data_for_plotting = defaultdict(lambda: defaultdict(list))
    for series in data_series_list:
        if series.get("load_balancing_mode") != lb_mode_filter:
            continue
        if series.get("recovery_mechanism") != recovery_filter:
            continue
        workload = series.get("workload", "Unknown")
        data_for_plotting["flows"][workload] = series.get("raw_data_for_cdf", {}).get("incast_flows_per_event", [])
        data_for_plotting["ips"][workload] = series.get("raw_data_for_cdf", {}).get("incast_ips_per_event", [])
        data_for_plotting["queue"][workload] = series.get("raw_data_for_cdf", {}).get("queue_bytes_per_event", [])

    if not data_for_plotting["flows"]:
        print(f"ℹ️ 没有找到匹配 LB={lb_mode_filter}, Recovery={recovery_filter} 的数据。")
        return

    # 如果 output_dir 没有指定，则使用 JSON 所在目录
    if output_dir is None:
        output_dir = os.path.dirname(json_path)

    # workload 名称映射
    workload_name_map = {
        "AliStorage2019": "Storage",
        "FbHdp2015": "Hadoop",
        "Solar2022": "RPC"
    }

    def rename_workloads(data_dict):
        new_dict = {}
        for k, v in data_dict.items():
            new_name = workload_name_map.get(k, k)  # 没有映射的保持原名
            new_dict[new_name] = v
        return new_dict

    # --- 绘图函数 ---
    def plot_cdf(data_dict, xlabel, filename, xscale='linear', convert_func=None):
        # 使用导入的 CDFPlot 类
        p = plot.CDFPlot()
        for workload, values in sorted(data_dict.items()):
            if values:
                if convert_func:
                    values = convert_func(values)
                p.plot(values, label=workload)
        p.ax.set_xlabel(xlabel, fontsize=35)
        p.ax.set_ylabel("CDF", fontsize=35)
        p.ax.tick_params(axis='x', labelsize=30)
        p.ax.tick_params(axis='y', labelsize=30)
        p.ax.set_xscale(xscale)
        p.ax.grid(True, ls="--", c='0.7')
        p.ax.legend(fontsize=25)
        # 禁用科学计数法显示
        p.ax.xaxis.set_major_formatter(ScalarFormatter())
        p.ax.ticklabel_format(style='plain', axis='x')
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, filename), bbox_inches='tight')
        plt.close()
        print(f"✅ 图表已保存至: {os.path.join(output_dir, filename)}")

    base_prefix = os.path.splitext(os.path.basename(json_path))[0]

    # 绘制三类图，并使用重命名后的 workload
    plot_cdf(rename_workloads(data_for_plotting["flows"]), "Incast Flows / PFC Event", f"{base_prefix}_flows.pdf")
    plot_cdf(rename_workloads(data_for_plotting["ips"]), "Number of Incast IPs per PFC Event", f"{base_prefix}_ips.pdf")
    plot_cdf(rename_workloads(data_for_plotting["queue"]), "Queue Size (MB) per PFC Event", f"{base_prefix}_queue.pdf", convert_func=lambda x: [v/1024/1024 for v in x])
def main():
    parser = argparse.ArgumentParser(description="绘制不同 workload 的 PFC Incast CDF 对比图")
    parser.add_argument("input_path", type=str, help="JSON 文件或目录路径")
    parser.add_argument("--output-dir", type=str, default=None, help="输出 PDF 目录，未指定则保存到 JSON 所在目录")
    args = parser.parse_args()

    if os.path.isfile(args.input_path):
        print(f"--- 正在处理 {args.input_path} ---")
        draw_workload_comparison(args.input_path, args.output_dir)
    elif os.path.isdir(args.input_path):
        json_files = glob.glob(os.path.join(args.input_path, "*.json"))
        if not json_files:
            print(f"⚠️ 在目录 {args.input_path} 中没有找到任何 JSON 文件")
            return
        print(f"找到 {len(json_files)} 个 JSON 文件，开始绘图...")
        for jf in json_files:
            print(f"--- 正在处理 {jf} ---")
            draw_workload_comparison(jf, args.output_dir)
        print("✅ 所有文件处理完成！")
    else:
        print(f"❌ 错误: {args.input_path} 不是有效文件或目录")

if __name__ == "__main__":
    main()