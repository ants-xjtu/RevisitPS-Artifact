import argparse
import os
import pandas as pd
import matplotlib.pyplot as plt

# Import the project's plotting library
import lib.py.plot.plot as plot


import os
import pandas as pd
import numpy as np

def read_fct_csv(filepath):
    """
    读取 CSV 并返回有效的 FCT 数据（排除空值、非数值和大于1000的值）。
    支持有表头或无表头的 CSV。
    """
    try:
        df = pd.read_csv(filepath)
        if 'fct' not in df.columns:
            df.columns = ['size', 'fct']
        fct_data = pd.to_numeric(df['fct'], errors='coerce').dropna()
        # fct_data = fct_data[fct_data <= 1000]
        return fct_data
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return pd.Series(dtype=float)

def print_fct_stats(data_dir, files):
    """
    打印每个 CSV 文件的 p50, p99, p99.9, p9999
    """
    percentiles = [50, 99, 99.9, 99.99]
    for filename in files:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            continue

        fct_data = read_fct_csv(filepath)
        if len(fct_data) == 0:
            print(f"No valid FCT data in {filename}")
            continue

        stats = np.percentile(fct_data, percentiles)
        print(f"\nStats for {filename}:")
        print(f"  p50     : {stats[0]:.3f}")
        print(f"  p99     : {stats[1]:.3f}")
        print(f"  p99.9   : {stats[2]:.3f}")
        print(f"  p9999   : {stats[3]:.3f}")


def read_fct_csv(filepath):
    """
    读取 CSV 并返回有效的 FCT 数据（排除空值、非数值和大于1000的值）。
    """
    try:
        df = pd.read_csv(filepath)
        if 'fct' not in df.columns:
            df.columns = ['size', 'fct']
        fct_data = pd.to_numeric(df['fct'], errors='coerce').dropna()
        fct_data = fct_data[fct_data <= 1000]
        return fct_data
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return pd.Series(dtype=float)

def plot_cdf(files_and_labels, data_dir, output_file, title):
    """
    绘制 CDF，去掉超过 p9999 的值
    """
    p = plot.CDFPlot()

    for filename, label in files_and_labels.items():
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            print(f"File not found, skipping: {filepath}")
            continue

        fct_data = read_fct_csv(filepath)
        if len(fct_data) == 0:
            print(f"No valid FCT data in {filename}")
            continue

        # 计算 p9999
        p9999 = np.percentile(fct_data, 99.99)
        # 只保留 <= p9999
        fct_data_filtered = fct_data[fct_data <= p9999]

        if len(fct_data_filtered) > 0:
            p.plot(fct_data_filtered.tolist(), label=label)
            print(f"Plotted {filename} (filtered p9999={p9999:.3f})")
        else:
            print(f"Warning: All data filtered out in {filename}")

    plt.xlabel(r"Flow Completion Time ($\mu$s)")
    p.ax.set_xscale('log')
    p.ax.set_xlim(left=10)
    p.ax.legend(fontsize=20)
    # p.ax.set_title(title, fontsize=16)
    plt.tight_layout()

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    plt.close()
    print(f"✅ Chart saved to: {output_file}\n")


def plot_drop_rate_cdf(data_dir, output_dir):
    files_and_labels = {
        'AR_inorder.csv': 'RTO + GBN (No Drop)',
        'AR_drop_10e-6.csv': 'RTO + GBN (Drop 1e-6)',
        'AR_drop_10e-5.csv': 'RTO + GBN (Drop 1e-5)',
        'AR_drop_10e-4.csv': 'RTO + GBN (Drop 1e-4)',
        'AR_drop_10e-3.csv': 'RTO + GBN (Drop 1e-3)',
    }
    print("--- Generating Drop Rate Comparison CDF ---")
    print_fct_stats(data_dir, files_and_labels)
    output_file = os.path.join(output_dir, "fct_cdf_drop_rate_comparison.pdf")
    plot_cdf(files_and_labels, data_dir, output_file, "CDF of FCT: Impact of Drop Rate")


def plot_ooo_comparison_cdf(data_dir, output_dir):
    files_and_labels = {
        'AR_inorder.csv': 'NAK + GBN (In-Order)',
        'noAR_OoO.csv': 'NAK + GBN (OoO)',
        'SR_OoO.csv': 'NAK + SR (OoO)',
        'AR_OoO.csv': 'RTO + GBN (OoO)',
    }
    print("--- Generating Out-of-Order Comparison CDF ---")
    output_file = os.path.join(output_dir, "fct_cdf_ooo_comparison.pdf")
    plot_cdf(files_and_labels, data_dir, output_file, "CDF of FCT: Comparison of OoO Mechanisms")


def main():
    parser = argparse.ArgumentParser(
        description="Generate CDF plots for FCT data from CSV files."
    )
    parser.add_argument(
        "data_directory_arg",
        type=str,
        help="Path to the data directory (relative or absolute)."
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_directory_arg)
    # ⚡ 固定输出目录
    output_dir = os.path.join(os.path.dirname(__file__), "testbed", "testbed_fct2")

    if not os.path.isdir(data_dir):
        print(f"Error: Provided directory is invalid: '{data_dir}'")
        return

    plot_drop_rate_cdf(data_dir, output_dir)
    plot_ooo_comparison_cdf(data_dir, output_dir)


if __name__ == '__main__':
    main()
