#!/usr/bin/python3
import matplotlib.pyplot as plt
import os
import io
import pandas as pd
import sys
import argparse
import click
from conf_parser.yaml_parser import TestConfParser


def load_data(file_path):
    """
    从包含 RDMA ibv 输出的文件中读取表格（从 '#bytes' 行开始）。
    返回 DataFrame，仅包含两列：Time[sec] (float) 和 BW_Gb_s (float)。
    如果文件中没有有效数据，则返回一个空的 DataFrame。
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except IOError as e:
        print(f"❌ 错误: 无法读取文件 {file_path}: {e}")
        return pd.DataFrame(columns=["Time[sec]", "BW_Gb_s"])

    # 找到 "#bytes" 那一行（表头）
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("#bytes"):
            start_idx = i
            break

    if start_idx is None:
        # 如果找不到表头，直接返回空 DataFrame
        print(f"⚠️ 警告: 在文件 {file_path} 中未找到数据头 '#bytes'。")
        return pd.DataFrame(columns=["Time[sec]", "BW_Gb_s"])

    # 取表格数据（从表头下一行开始）
    data_lines = lines[start_idx + 1 :]

    rows = []
    for line in data_lines:
        s = line.strip()
        if not s or not s[0].isdigit():
            continue
        
        tokens = s.split()
        if len(tokens) < 4:
            continue
        
        # 只取前 4 列，避免因表头拆分不一致导致的问题
        rows.append(tokens[:4])

    if not rows:
        # 如果没有解析到任何数据行，返回空 DataFrame
        return pd.DataFrame(columns=["Time[sec]", "BW_Gb_s"])

    # 构造 DataFrame
    df = pd.DataFrame(rows, columns=["bytes", "iterations", "Time[sec]", "BW_Gb_s"])

    # 将 Time[sec] 和 BW_Gb_s 列转换为数值类型，无法转换的将变为 NaN
    df["Time[sec]"] = pd.to_numeric(df["Time[sec]"], errors="coerce")
    df["BW_Gb_s"] = pd.to_numeric(df["BW_Gb_s"], errors="coerce")

    # 丢弃任何包含 NaN 的行，并重置索引
    df = df.dropna(subset=["Time[sec]", "BW_Gb_s"]).reset_index(drop=True)

    # 只返回需要的两列
    return df[["Time[sec]", "BW_Gb_s"]]


def generate_avg_csv(root_folder, output):
    """
    遍历 root_folder 下的子目录，
    每个子目录里的 txt 文件按相同的行号（索引）对齐，
    保留 Time[sec] 列，计算 BW_Gb_s 总和，输出到 CSV 文件。
    """
    os.makedirs(output, exist_ok=True)
    csv_paths = []
    print(root_folder)
    txt_files = [
        os.path.join(root_folder, f)
        for f in os.listdir(root_folder)
        if f.endswith(".log") and os.path.isfile(os.path.join(root_folder, f))
    ]
    print(txt_files)
    if not txt_files:
        return
    # 加载所有数据，并过滤掉空的 DataFrame
    dfs = [load_data(f) for f in txt_files]
    dfs = [df for df in dfs if not df.empty]
    if not dfs:
        print(f"ℹ️ 在目录 {root_folder} 中未找到有效的 log 数据文件，已跳过。")
        return
    # *** 关键改进：处理行数不一致 ***
    # 1. 找到所有 DataFrame 中最短的长度
    min_len = min(len(df) for df in dfs)
    if min_len == 0:
        print(f"ℹ️ 在目录 {root_folder} 的文件中没有共同的数据行，已跳过。")
        return
    # 2. 将所有 DataFrame 截断到相同的最小长度，确保对齐
    dfs_aligned = [df.head(min_len) for df in dfs]
    
    print(f"  -> 在目录 {root_folder} 中，文件按最短长度 {min_len} 行进行了对齐。")
    # 保留第一列 Time[sec]（现在所有文件的时间列都已对齐）
    time_col = dfs_aligned[0]["Time[sec]"]
    # 取所有对齐后的 BW_Gb_s 列
    bw_cols = [df["BW_Gb_s"] for df in dfs_aligned]
    # 计算总带宽，此时不会因为长度不一而产生 NaN
    total_bw = pd.concat(bw_cols, axis=1).sum(axis=1)
    # 构造输出 DataFrame
    out_df = pd.DataFrame({
        "Time[sec]": time_col,
        "BW_Gb_s_total": total_bw
    })
    csv_path = os.path.join(output, f"total.csv")
    out_df.to_csv(csv_path, index=False)
    csv_paths.append(csv_path)
    print(f"✅ 已生成 {csv_path}")

    return csv_paths


def plot_from_csv(csv_files, output, max_time=10):
    """
    根据生成的 avg.csv 文件绘制吞吐量曲线。
    """
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "axes.labelsize": 16,
        "axes.titlesize": 18,
        "legend.fontsize": 10,
        "xtick.labelsize": 14,
        "ytick.labelsize": 14,
        "lines.linewidth": 2.5,
        "figure.dpi": 300
    })

    fig, ax = plt.subplots(figsize=(10, 6))
    styles = ['-', '--', '-.', ':']
    color_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']

    for i, csv_file in enumerate(csv_files):
        df = pd.read_csv(csv_file)
        df_filtered = df[(df['Time[sec]'] >= 5) & (df['Time[sec]'] <= max_time)]
        base_name = os.path.splitext(os.path.basename(csv_file))[0]
        
        # 在计算平均值前检查 DataFrame 是否为空
        if df_filtered.empty:
            print(f"⚠️ {base_name} 在 5s 到 {max_time}s 时间范围内没有数据，无法计算平均值。")
            mean_throughput = 0 # 或者 float('nan')
        else:
            mean_throughput = df_filtered['BW_Gb_s_total'].mean()

        # 格式化输出，避免直接打印 nan
        if pd.isna(mean_throughput):
            print(f"{base_name} avg throughput: NaN")
        else:
            print(f"{base_name} avg throughput: {mean_throughput:.2f} Gb/s")
        
        ax.plot(
            df_filtered['Time[sec]'],
            df_filtered['BW_Gb_s_total'],
            linestyle=styles[i % len(styles)],
            color=color_cycle[i % len(color_cycle)],
            alpha=0.85,
            label=base_name
        )

    ax.set_title(f'RDMA Write Throughput (First {max_time}s)', pad=15)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Throughput (Gb/s)')
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', linestyle='--', alpha=0.7)

    ax.legend(
        loc='center left',
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        ncol=1
    )

    fig.tight_layout(rect=[0, 0, 0.8, 1])
    os.makedirs(output, exist_ok=True)
    out_png = os.path.join(output, f"comparison_first{max_time}s.png")
    out_pdf = os.path.join(output, f"comparison_first{max_time}s.pdf")
    plt.savefig(out_png, bbox_inches='tight')
    plt.savefig(out_pdf, bbox_inches='tight')
    print(f"📊 图像已保存至 {out_png}, {out_pdf}")

def plot_per_file_throughput(root_folder, output, min_time=10, max_time=15):
    """
    遍历 root_folder 下的所有 .log 文件，
    为每个文件单独输出一张 throughput 随时间变化的图片。
    """
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "axes.labelsize": 16,
        "axes.titlesize": 18,
        "legend.fontsize": 10,
        "xtick.labelsize": 14,
        "ytick.labelsize": 14,
        "lines.linewidth": 2.5,
        "figure.dpi": 300
    })

    txt_files = sorted([
        os.path.join(root_folder, f)
        for f in os.listdir(root_folder)
        if f.endswith(".log") and os.path.isfile(os.path.join(root_folder, f))
    ])

    if not txt_files:
        print(f"❌ 在目录 {root_folder} 中未找到 .log 文件。")
        return

    os.makedirs(output, exist_ok=True)

    for fpath in txt_files:
        df = load_data(fpath)
        if df.empty:
            print(f"⚠️ 文件 {fpath} 无有效数据，已跳过。")
            continue

        df_filtered = df[(df['Time[sec]'] >= min_time) & (df['Time[sec]'] <= max_time)]
        if df_filtered.empty:
            print(f"⚠️ 文件 {fpath} 在 {min_time}s~{max_time}s 范围内无数据，已跳过。")
            continue

        label = os.path.splitext(os.path.basename(fpath))[0]
        mean_bw = df_filtered['BW_Gb_s'].mean()
        print(f"{label} avg throughput: {mean_bw:.2f} Gb/s")

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(
            df_filtered['Time[sec]'],
            df_filtered['BW_Gb_s'],
            alpha=0.85,
            label=f"{label} (avg {mean_bw:.1f} Gb/s)"
        )

        ax.set_title(f'{label} Throughput ({min_time}s~{max_time}s)', pad=15)
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Throughput (Gb/s)')
        ax.set_ylim(bottom=0)
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        ax.legend(loc='best', frameon=False)
        fig.tight_layout()

        out_png = os.path.join(output, f"{label}_throughput_{min_time}s_{max_time}s.png")
        out_pdf = os.path.join(output, f"{label}_throughput_{min_time}s_{max_time}s.pdf")
        plt.savefig(out_png, bbox_inches='tight')
        plt.savefig(out_pdf, bbox_inches='tight')
        plt.close(fig)
        print(f"📊 图像已保存至 {out_png}, {out_pdf}")


@click.group()
def cli():
    """Remote RDMA test tool with various test commands"""
    pass

@cli.command()
def plot_throughput(test_conf_parser: TestConfParser):
    test_conf = test_conf_parser.get()
    plot_conf = test_conf.applications.plot
    root_folder = plot_conf.input_folder
    output_folder = plot_conf.output_folder
    max_time = plot_conf.max_time

    # 1. 生成聚合后的 CSV
    csv_files = generate_avg_csv(root_folder, output_folder)
    if not csv_files:
        print("❌ 未生成任何 CSV 文件，请检查输入目录及其内容。")
        return

    # 2. 根据 CSV 绘图
    plot_from_csv(csv_files, output_folder, max_time=max_time)

    # 3. 绘制每个文件各自的 throughput 随时间变化曲线
    plot_per_file_throughput(root_folder, output_folder, min_time=10, max_time=12)
    