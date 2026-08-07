import matplotlib.pyplot as plt
import numpy as np
import os
import argparse
import pandas as pd

OFFSET = 0  # 每个FCT减去的基准值

def parse_latency_file(filepath):
    """
    Safely parses a latency CSV file.
    - Handles missing files.
    - Handles rows with invalid values.
    - Returns a list of latency values (FCTs).
    """
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: File not found at '{filepath}'. Skipping.")
        return []

    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"⚠️ Warning: Failed to read CSV '{filepath}': {e}")
        return []

    if 'fct' not in df.columns:
        print(f"⚠️ Warning: No 'fct' column found in '{filepath}'.")
        return []

    fcts = []
    for val in pd.to_numeric(df['fct'], errors='coerce'):
        if pd.notna(val):
            val = val - OFFSET
            if val < 8 or val > 200:
                print(val)
                continue
            if val >= 0:  # 避免负数
                fcts.append(val)

    return fcts


def plot_cdf(filepaths, output_filename='rdma_latency_cdf.pdf'):
    """
    Generates and saves a CDF plot for multiple files.
    """
    # --- 更适合论文的风格 ---
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(3.4, 2.6))  # 单栏大小（inches）

    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    linestyles = ['-', '--', '-.', ':']

    for i, filepath in enumerate(filepaths):
        fcts = parse_latency_file(filepath)
        if not fcts:
            print(f"No valid data for '{filepath}'. Skipping plot.")
            continue

        fcts_sorted = np.sort(np.array(fcts))
        cdf = np.arange(1, len(fcts_sorted) + 1) / len(fcts_sorted)

        # Percentiles
        p50 = np.percentile(fcts_sorted, 50)
        p99 = np.percentile(fcts_sorted, 99)
        p999 = np.percentile(fcts_sorted, 99.9)

        label = (
            f"{os.path.basename(filepath)}\n"
            f"(P50={p50:.1f}, P99={p99:.1f})"
        )

        ax.plot(
            fcts_sorted, cdf,
            label=label,
            color=colors[i % len(colors)],
            linestyle=linestyles[i % len(linestyles)],
            linewidth=1.5
        )

    # --- 论文友好字体大小 ---
    ax.set_xscale('log')
    ax.set_xlabel('Flow Completion Time (µs)', fontsize=9)
    ax.set_ylabel('Cumulative Probability', fontsize=9)

    ax.tick_params(axis='both', which='major', labelsize=8)
    ax.tick_params(axis='both', which='minor', labelsize=7)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    ax.legend(loc='lower right', fontsize=7, frameon=False)

    fig.tight_layout(pad=0.2)
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')  # 高分辨率保存
    print(f"\n✅ Plot successfully saved to '{output_filename}'")


def main():
    parser = argparse.ArgumentParser(description="Plot CDFs of RDMA latency logs.")
    parser.add_argument('files', nargs='+', help="Paths to latency log files")
    parser.add_argument('--out', default='rdma_latency_cdf.pdf', help="Output filename (default: rdma_latency_cdf.pdf)")
    args = parser.parse_args()

    plot_cdf(args.files, args.out)

if __name__ == "__main__":
    main()
