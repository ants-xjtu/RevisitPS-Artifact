#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys

def format_bytes(num):
    """
    将字节数格式化为易于阅读的 K, M 格式，以便在输出中显示。
    """
    num = float(num)
    if num < 1024:
        return f"{num}B"
    elif num < 1024**2:
        return f"{num/1024:.1f}K"
    elif num < 1024**3:
        return f"{num/1024**2:.1f}M"
    else:
        return f"{num/1024**3:.1f}G"

def compare_fct_performance(json_path, combo1_label, combo2_label):
    """
    加载FCT JSON文件，查找两个指定的组合，并逐点比较它们的性能。

    Args:
        json_path (str): 输入的JSON文件路径。
        combo1_label (str): 第一个组合的标签（基准），格式为 "LB(Recovery)"。
        combo2_label (str): 第二个组合的标签（比较对象）。
    """
    # --- 1. 加载和验证JSON文件 ---
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 错误: 文件未找到 -> {json_path}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"❌ 错误: 无法解析JSON文件 -> {json_path}")
        sys.exit(1)

    data_series_list = data.get("data_series", [])
    if not data_series_list:
        print(f"⚠️ 警告: 在文件 {json_path} 中找不到 'data_series'。")
        return

    # --- 2. 查找指定的两个数据系列 ---
    series1_data = None
    series2_data = None

    for series in data_series_list:
        # 从数据中动态构建标签以进行匹配
        current_label = f"{series.get('load_balancing_mode', 'N/A')}({series.get('recovery_mechanism', 'N/A')})"
        if current_label == combo1_label:
            series1_data = series
        if current_label == combo2_label:
            series2_data = series

    # 检查是否找到了两个系列
    if not series1_data:
        print(f"❌ 错误: 在文件中找不到组合 '{combo1_label}'。")
        return
    if not series2_data:
        print(f"❌ 错误: 在文件中找不到组合 '{combo2_label}'。")
        return

    print(f"✅ 已成功找到两个待比较的组合。")
    print(f"   - 基准 (A): {combo1_label}")
    print(f"   - 比较 (B): {combo2_label}")
    print("-" * 60)
    print("正在计算性能差异 (B vs A)...")
    print("公式: (B - A) / A * 100%")
    print("负值表示性能提升（慢速比降低），正值表示性能下降。")
    print("-" * 60)

    # --- 3. 逐点比较并打印结果 ---
    flow_sizes = series1_data.get("flow_size_buckets_bytes", [])
    avg1_list = series1_data.get("avg_fct_slowdown", [])
    avg2_list = series2_data.get("avg_fct_slowdown", [])
    p99_1_list = series1_data.get("p99_fct_slowdown", [])
    p99_2_list = series2_data.get("p99_fct_slowdown", [])

    # 打印表头
    print(f"{'Flow Size':<15} | {'Avg Slowdown Diff (%)':>25} | {'P99 Slowdown Diff (%)':>25}")
    print(f"{'-'*15:<15} | {'-'*25:>25} | {'-'*25:>25}")

    for i in range(len(flow_sizes)):
        size = flow_sizes[i]
        avg1, avg2 = avg1_list[i], avg2_list[i]
        p99_1, p99_2 = p99_1_list[i], p99_2_list[i]

        # 计算差异百分比，处理除以零的情况
        avg_diff = ((avg2 - avg1) / avg1 * 100) if avg1 != 0 else float('inf')
        p99_diff = ((p99_2 - p99_1) / p99_1 * 100) if p99_1 != 0 else float('inf')

        # 格式化输出
        size_str = format_bytes(size)
        avg_diff_str = f"{avg_diff:+.2f}" if avg_diff != float('inf') else "N/A"
        p99_diff_str = f"{p99_diff:+.2f}" if p99_diff != float('inf') else "N/A"

        print(f"{size_str:<15} | {avg_diff_str:>25} | {p99_diff_str:>25}")

def main():
    """主函数，用于解析命令行参数并启动比较过程。"""
    parser = argparse.ArgumentParser(
        description='比较FCT数据文件中两个(LB+Recovery)组合的性能。',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'json_file',
        type=str,
        help='由FCT解析脚本生成的JSON文件的路径。'
    )
    parser.add_argument(
        'combo1',
        type=str,
        help='作为基准的第一个组合。\n格式: "LB(Recovery)", 例如: "ECMP(NAK+GBN)"'
    )
    parser.add_argument(
        'combo2',
        type=str,
        help='要与基准进行比较的第二个组合。\n格式: "LB(Recovery)", 例如: "AR(RTO+GBN)"'
    )
    args = parser.parse_args()

    compare_fct_performance(args.json_file, args.combo1, args.combo2)

if __name__ == "__main__":
    main()