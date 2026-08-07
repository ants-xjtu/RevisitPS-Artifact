#!/usr/bin/python3
import os
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import click
import glob
from concurrent.futures import ProcessPoolExecutor, as_completed
from conf_parser.yaml_parser import TestConfParser
from io import StringIO
THRESHOLD = 60 * 1024  # 60KB


def _process_single_file(file_path):
    """处理单个 log 文件，保留原有解析逻辑"""
    prev_end_time = None
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
        start = 0
        for i, line in enumerate(lines):
            if line.startswith("size,start_time,end_time"):
                start = i
                break
        csv_text = "".join(lines[start:-1])
        df = pd.read_csv(StringIO(csv_text))

        # 检查必需列
        if {"size", "start_time", "end_time"}.issubset(df.columns):
            # 确保按 start_time 排序
            df = df.sort_values(by="start_time").reset_index(drop=True)

            fct_list = []
            for _, row in df.iterrows():
                start = row["start_time"]
                end = row["end_time"]

                if prev_end_time is not None and start < prev_end_time:
                    fct = end - prev_end_time
                else:
                    fct = end - start
                if fct > 0:
                    fct_list.append(fct)
                if fct < 0:
                    pass
                #   print(f'start_time:{start}, end_time:{end}')
                prev_end_time = end  # 更新上一条流的结束时间

            df_result = pd.DataFrame({
                "size": df["size"],
                "fct": fct_list
            })

            return df_result, None
        else:
            return None, f"{os.path.basename(file_path)} 缺少 size/start_time/end_time 列，已跳过"

    except Exception as e:
        return None, f"读取 {os.path.basename(file_path)} 失败: {e}"


def process_and_merge(input_dir, output_file="merged.csv", max_workers=None):
    """
    处理并合并目录下的所有 log 文件

    Args:
        input_dir: 输入目录路径
        output_file: 输出文件路径
        max_workers: 并行处理的最大进程数，None 表示使用 CPU 核心数
    """
    all_data = []

    # 扫描目录下的所有 log 文件
    files = glob.glob(os.path.join(input_dir, "*.log"))
    if not files:
        print(f"[WARN] 在目录 {input_dir} 下没有找到 log 文件")
        return

    # 使用多进程并行处理文件
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_file, f): f for f in files}

        for future in as_completed(futures):
            df_result, error_msg = future.result()
            if error_msg:
                print(error_msg)
            elif df_result is not None and not df_result.empty:
                all_data.append(df_result)

    if all_data:
        merged = pd.concat(all_data, ignore_index=True)
        merged.to_csv(output_file, index=False)
        print(f"[OK] 已生成合并文件: {output_file}")
    else:
        print("[WARN] 没有生成任何数据")

def analysis(csv_file, output):
    os.makedirs(os.path.dirname(output), exist_ok=True)

    output_mean = os.path.join(output, "mean.png")
    output_p99 = os.path.join(output, "p99.png")
    output_csv = os.path.join(output, "stats.csv")

    # =========================
    # 读取 CSV
    # =========================
    if not os.path.exists(csv_file):
        raise FileNotFoundError(f"文件不存在: {csv_file}")

    df = pd.read_csv(csv_file)
    if not {"size", "fct"}.issubset(df.columns):
        raise ValueError(f"{csv_file} 缺少 size 或 fct 列")

    # 过滤异常值（可选）
    threshold = 1e9
    df = df[~(df >= threshold).any(axis=1)]

    # 分组
    small_group = df[df['size'] < THRESHOLD]['fct']
    large_group = df[df['size'] >= THRESHOLD]['fct']

    print("\n前20个最大 FCT 值（小包）:")
    # print(small_group.nlargest(20).to_list())

    print("\n前20个最大 FCT 值（大包）:")
    # print(large_group.nlargest(20).to_list())
    def calc_stats(series):
        if len(series) == 0:
            return {
                'mean': np.nan,
                'p50': np.nan,
                'p60': np.nan,
                'p70': np.nan,
                'p80': np.nan,
                'p90': np.nan,
                'p99': np.nan
            }
        return {
            'mean': series.mean(),
            'p50': np.percentile(series, 50),
            'p60': np.percentile(series, 60),
            'p70': np.percentile(series, 70),
            'p80': np.percentile(series, 80),
            'p90': np.percentile(series, 90),
            'p99': np.percentile(series, 99)
        }

    stats_small = calc_stats(small_group)
    stats_large = calc_stats(large_group)

    mean_small = stats_small['mean']
    mean_large = stats_large['mean']
    p99_small = stats_small['p99']
    p99_large = stats_large['p99']

    # =========================
    # 绘图
    # =========================
    x = np.arange(1)  # 单文件
    width = 0.35
    labels = [os.path.basename(csv_file)]

    # 平均值图
    fig1, ax1 = plt.subplots(figsize=(6, 4))
    ax1.bar(x - width/2, [mean_small], width, label='Size < 60KB', color='skyblue', edgecolor='black')
    ax1.bar(x + width/2, [mean_large], width, label='Size >= 60KB', color='lightcoral', edgecolor='black')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha='right')
    ax1.set_ylabel('Average FCT (μs)')
    ax1.set_title('Average FCT')
    ax1.legend()
    ax1.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(output_mean, dpi=300)
    plt.show()
    print(f"✅ 平均 FCT 图已保存: {output_mean}")

    # 99% 图
    fig2, ax2 = plt.subplots(figsize=(6, 4))
    ax2.bar(x - width/2, [p99_small], width, label='Size < 60KB', color='skyblue', edgecolor='black')
    ax2.bar(x + width/2, [p99_large], width, label='Size >= 60KB', color='lightcoral', edgecolor='black')
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=30, ha='right')
    ax2.set_ylabel('99%ile FCT (μs)')
    ax2.set_title('99th Percentile FCT')
    ax2.legend()
    ax2.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(output_p99, dpi=300)
    plt.show()
    print(f"✅ 99% FCT 图已保存: {output_p99}")

    # =========================
    # 输出统计表格
    # =========================
    results_df = pd.DataFrame({
        "File": [os.path.basename(csv_file)],
        "Mean_Small": [mean_small],
        "Mean_Large": [mean_large],
        "P50_Small": [stats_small['p50']],
        "P50_Large": [stats_large['p50']],
        "P60_Small": [stats_small['p60']],
        "P60_Large": [stats_large['p60']],
        "P70_Small": [stats_small['p70']],
        "P70_Large": [stats_large['p70']],
        "P80_Small": [stats_small['p80']],
        "P80_Large": [stats_large['p80']],
        "P90_Small": [stats_small['p90']],
        "P90_Large": [stats_large['p90']],
        "P99_Small": [p99_small],
        "P99_Large": [p99_large],
    })
    results_df.to_csv(output_csv, index=False)
    print(f"✅ 统计结果已保存: {output_csv}")
    print("\n=== 统计结果 ===")
    print(results_df.to_string(index=False))

    # 输出详细的分位数信息
    print("\n=== 分位数详细信息 ===")
    print(f"小包 (Size < 60KB):")
    print(f"  Mean: {stats_small['mean']:.2f} μs")
    print(f"  P50:  {stats_small['p50']:.2f} μs")
    print(f"  P60:  {stats_small['p60']:.2f} μs")
    print(f"  P70:  {stats_small['p70']:.2f} μs")
    print(f"  P80:  {stats_small['p80']:.2f} μs")
    print(f"  P90:  {stats_small['p90']:.2f} μs")
    print(f"  P99:  {stats_small['p99']:.2f} μs")
    print(f"\n大包 (Size >= 60KB):")
    print(f"  Mean: {stats_large['mean']:.2f} μs")
    print(f"  P50:  {stats_large['p50']:.2f} μs")
    print(f"  P60:  {stats_large['p60']:.2f} μs")
    print(f"  P70:  {stats_large['p70']:.2f} μs")
    print(f"  P80:  {stats_large['p80']:.2f} μs")
    print(f"  P90:  {stats_large['p90']:.2f} μs")
    print(f"  P99:  {stats_large['p99']:.2f} μs")

@click.group()
def cli():
    pass

@cli.command()
def analysis_fct(test_conf_parser: TestConfParser):
    test_conf = test_conf_parser.get()
    analysis_conf = test_conf.applications.analysis
    input_folder = analysis_conf.input_folder
    output_folder = analysis_conf.output_folder
    os.makedirs(output_folder, exist_ok=True)
    output_merge_file = os.path.join(output_folder, "merged.csv")
    process_and_merge(input_folder, output_merge_file)
    analysis(output_merge_file, output_folder)

