import matplotlib.pyplot as plt
import numpy as np
import argparse
import os
from collections import Counter  # <-- 确保加了这一行


def parse_fct_file(file_path):
    finish_times_ms = []
    fct_times_ms = []
    sizes_bytes = []
    dip_list = []
    sip_list = []  # <-- 加入源地址

    with open(file_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 9:
                continue
            try:
                sip = parts[0]  # 源地址
                dip = parts[1]  # 目的地址
                size_bytes = int(parts[4])
                start_time_ns = int(parts[5])
                fct_ns = int(parts[6])
                finish_time_ns = start_time_ns + fct_ns

                adjusted_finish_ms = (finish_time_ns - 2_000_000_000) / 1e6
                adjusted_fct_ms = fct_ns / 1e6

                sizes_bytes.append(size_bytes)
                finish_times_ms.append(adjusted_finish_ms)
                fct_times_ms.append(adjusted_fct_ms)
                dip_list.append(dip)
                sip_list.append(sip)  # <-- 存储源地址
            except ValueError:
                continue

    return (
        np.array(finish_times_ms),
        np.array(fct_times_ms),
        np.array(sizes_bytes),
        np.array(dip_list),
        np.array(sip_list),  # <-- 返回源地址
    )


def analyze_unfinished_flows(finish_times, sizes, dips, sips, threshold=60, output_prefix="flow_output"):
    mask = finish_times > threshold
    unfinished_sizes = sizes[mask]
    unfinished_dips = dips[mask]
    unfinished_sips = sips[mask]

    total_flows = len(finish_times)
    unfinished_flows = len(unfinished_sizes)

    if unfinished_flows == 0:
        print(f"No unfinished flows over {threshold} ms found.")
        return

    # 按生成格式写入文件
    output_file = f"{output_prefix}_unfinished_flows.csv"
    flow_lines = [
        f"{sip} {dip} 3 {size} 2.00000034\n"
        for sip, dip, size in zip(unfinished_sips, unfinished_dips, unfinished_sizes)
    ]
    with open(output_file, 'w') as f:
        f.write(f"{len(flow_lines)}\n")  # 第一行写 flow 数量
        f.writelines(flow_lines)

    print(f"Saved unfinished flows to: {output_file}")

    # 统计信息
    count_counter = Counter(unfinished_dips)
    size_counter = Counter()
    for dip, size in zip(unfinished_dips, unfinished_sizes):
        size_counter[dip] += size

    print(f"\nUnfinished Flows (> {threshold} ms):")
    print(f"Total flows: {total_flows}, Unfinished flows: {unfinished_flows} ({unfinished_flows/total_flows*100:.2f}%)")
    print(f"By destination (dip):")

    for dip, count in count_counter.most_common():
        size_bytes = size_counter[dip]
        print(f"  DIP: {dip} - Count: {count} ({count/unfinished_flows*100:.2f}%), Size: {size_bytes} bytes ({size_bytes/sum(unfinished_sizes)*100:.2f}%)")

def plot_histogram_finish_time(finish_times, output_prefix):
    plt.figure(figsize=(8, 4))
    plt.hist(finish_times, bins=30, color='skyblue', edgecolor='black')
    plt.axvspan(60, 100, color='red', alpha=0.3, label='60ms ~ 100ms')
    plt.xlabel('Flow Finish Time (ms)')
    plt.ylabel('Number of Flows')
    plt.title('Histogram of Flow Finish Times')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_hist_finish.png")
    plt.close()

def plot_cdf_finish_time(finish_times, output_prefix):
    plt.figure(figsize=(8, 4))
    sorted_times = np.sort(finish_times)
    cdf = np.arange(len(sorted_times)) / len(sorted_times)
    plt.plot(sorted_times, cdf, color='green', label='CDF')
    plt.axvline(60, color='red', linestyle='--', label='60 ms')
    plt.axvline(100, color='red', linestyle='--', label='100 ms')
    plt.xlabel('Flow Finish Time (ms)')
    plt.ylabel('CDF')
    plt.title('CDF of Flow Finish Times')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_cdf_finish.png")
    plt.close()

def plot_scatter_size_vs_finish(finish_times, sizes, output_prefix):
    plt.figure(figsize=(8, 4))
    plt.scatter(finish_times, sizes / 1024, s=10, alpha=0.5)
    plt.axvspan(60, 100, color='red', alpha=0.2, label='60ms ~ 100ms')
    plt.xlabel('Flow Finish Time (ms)')
    plt.ylabel('Flow Size (KB)')
    plt.title('Flow Size vs Finish Time')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_scatter_size_vs_finish.png")
    plt.close()

def plot_fct_distribution(fct_times, output_prefix):
    plt.figure(figsize=(8, 4))
    plt.hist(fct_times, bins=30, color='orange', edgecolor='black')
    plt.xlabel('Flow Completion Time (ms)')
    plt.ylabel('Number of Flows')
    plt.title('Histogram of Flow Completion Times (FCT)')
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_hist_fct.png")
    plt.close()

def plot_total_size_per_bucket(finish_times_ms, sizes_bytes, output_prefix, bin_size_ms=10):
    # 转为 numpy，确保对齐
    finish_times_ms = np.array(finish_times_ms)
    sizes_kb = np.array(sizes_bytes) / 1024.0

    # 设置时间桶：从最小到最大时间，每 bin_size_ms 为一桶
    max_time = np.max(finish_times_ms)
    bins = np.arange(0, max_time + bin_size_ms, bin_size_ms)

    # 使用 numpy 的 histogram 累计大小（不是数量）
    total_size_per_bin, _ = np.histogram(finish_times_ms, bins=bins, weights=sizes_kb)

    # 用桶中心作为横轴
    bin_centers = (bins[:-1] + bins[1:]) / 2

    plt.figure(figsize=(10, 4))
    plt.bar(bin_centers, total_size_per_bin, width=bin_size_ms * 0.9, color='purple', edgecolor='black')
    plt.axvspan(60, 100, color='red', alpha=0.3, label='60ms ~ 100ms')
    plt.xlabel('Flow Finish Time (ms)')
    plt.ylabel('Total Completed Size (KB)')
    plt.title(f'Total Flow Size Completed per {bin_size_ms}ms Bucket')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{output_prefix}_size_per_bucket.png")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Analyze and visualize flow finish time distributions.')
    parser.add_argument('filepath', type=str, help='Path to FCT log file')
    parser.add_argument('--output', type=str, default='flow_output', help='Prefix for output image files')
    parser.add_argument('--tmin', type=float, default=None, help='Minimum finish time (ms) to include')
    parser.add_argument('--tmax', type=float, default=None, help='Maximum finish time (ms) to include')

    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: File '{args.filepath}' does not exist.")
        return

    finish_times, fct_times, sizes, dips, sips = parse_fct_file(args.filepath)

    if len(finish_times) == 0:
        print("No valid data found in the file.")
        return

    # 时间过滤
    if args.tmin is not None or args.tmax is not None:
        mask = np.ones_like(finish_times, dtype=bool)
        if args.tmin is not None:
            mask &= finish_times >= args.tmin
        if args.tmax is not None:
            mask &= finish_times <= args.tmax

        num_filtered_out = np.sum(~mask)
        print(f"Filtered out {num_filtered_out} flows outside [{args.tmin}, {args.tmax}] ms.")

        finish_times = finish_times[mask]
        fct_times = fct_times[mask]
        sizes = sizes[mask]
        dips = dips[mask]

    print(f"Using {len(finish_times)} flows in the selected time window.")

    # 统计80ms后未完成流的dip占比
    analyze_unfinished_flows(finish_times, sizes, dips, sips, threshold=00, output_prefix=args.output)

    # # 你已有的绘图函数调用
    # plot_histogram_finish_time(finish_times, args.output)
    # plot_cdf_finish_time(finish_times, args.output)
    # plot_scatter_size_vs_finish(finish_times, sizes, args.output)
    # plot_fct_distribution(fct_times, args.output)
    # plot_total_size_per_bucket(finish_times, sizes, args.output)

    # print(f"Saved plots with prefix: {args.output}_*.png")

if __name__ == '__main__':
    main()