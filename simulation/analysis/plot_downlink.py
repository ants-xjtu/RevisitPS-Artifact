import pandas as pd
import matplotlib.pyplot as plt
import argparse
import math
import os

def parse_and_plot(file_id, smooth_window=3, group_size=8):
    # 构造文件路径
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mix", "output"))
    filepath = os.path.join(base_path, file_id, f"{file_id}_out_downlink.txt")
    output_prefix = f"downlink_throughput_{file_id}"

    if not os.path.isfile(filepath):
        print(f"❌ 错误：文件不存在: {filepath}")
        return

    print(f"📂 正在读取文件: {filepath}")
    df = pd.read_csv(filepath, header=None, names=["time_ns", "tor_id", "dev_id", "tx_bytes"])

    # 时间转换为 ms，减去 2s 起点
    df["time_ms"] = (df["time_ns"] - 2_000_000_000) / 1e6

    throughput_records = []

    for (tor_id, dev_id), group in df.groupby(["tor_id", "dev_id"]):
        group = group.sort_values("time_ms").copy()
        group["delta_bytes"] = group["tx_bytes"].diff()
        group["delta_time_ms"] = group["time_ms"].diff()

        group = group[(group["delta_bytes"] >= 0) & (group["delta_time_ms"] > 0)]

        group["throughput_Mbps_raw"] = (group["delta_bytes"] * 8) / (group["delta_time_ms"] * 1000)
        group["throughput_Mbps"] = group["throughput_Mbps_raw"].rolling(window=smooth_window, min_periods=1).mean()
        group["label"] = f"ToR {tor_id} Dev {dev_id}"

        throughput_records.append(group)

    if not throughput_records:
        print("⚠️ No valid data found.")
        return

    all_data = pd.concat(throughput_records)
    all_labels = sorted(all_data["label"].unique())
    total_groups = math.ceil(len(all_labels) / group_size)

    for i in range(total_groups):
        selected_labels = all_labels[i * group_size : (i + 1) * group_size]
        plt.figure(figsize=(12, 6))
        for label in selected_labels:
            sub = all_data[all_data["label"] == label]
            plt.plot(sub["time_ms"], sub["throughput_Mbps"], label=label)
        plt.xlabel("Time (ms)")
        plt.ylabel("Throughput (Mbps)")
        plt.title(f"Downlink Throughput (Group {i}) - ID {file_id}")
        plt.grid(True)
        plt.legend(fontsize="small", ncol=2)
        plt.tight_layout()
        out_file = f"{output_prefix}_group{i}.png"
        plt.savefig(out_file)
        plt.close()
        print(f"✅ 图已保存: {out_file}")

def main():
    parser = argparse.ArgumentParser(description="Plot downlink throughput from log file (by ID)")
    parser.add_argument("id", help="Log file ID (e.g., 48007785)")
    parser.add_argument("--smooth", type=int, default=500, help="Rolling window size for smoothing")
    parser.add_argument("--group", type=int, default=8, help="Number of lines per figure")
    args = parser.parse_args()

    parse_and_plot(args.id, args.smooth, args.group)

if __name__ == "__main__":
    main()
