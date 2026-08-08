import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from io import StringIO
import sys
import os
import argparse

# === 0. Argument Parsing ===
parser = argparse.ArgumentParser(
    description="Analyze and visualize network throughput data from ns-3 simulations.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    'file_id',
    nargs='?',
    default=None,
    help="The ID of the file to process (e.g., '123').\n"
         "The script will look for a file named '<ID>_out_throughput.txt'."
)
parser.add_argument(
    '--no-plot',
    action='store_true',
    help="Disable plotting and instead calculate and display average throughput statistics."
)
args = parser.parse_args()

# === 1. 设置文件路径（使用 ID 自动构造） ===
base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mix", "output"))
file_id = args.file_id

if file_id:
    input_file_path = os.path.join(base_path, file_id, f"{file_id}_out_throughput.txt")
    print(f"📂 Will read from path: {input_file_path}")
else:
    input_file_path = "throughput.txt"
    print(f"⚠️ No ID specified, will use default file: '{input_file_path}'")
    print(f"   Hint: You can specify an ID like this: 'python {sys.argv[0]} <ID>'")

# === 2. 数据准备 ===
try:
    df = pd.read_csv(input_file_path, header=None, names=['time', 'hostId', 'accSendBytes', 'accAckedBytes'])
    print(f"✅ Successfully read {len(df)} rows of data.")
except FileNotFoundError:
    print(f"❌ Error: File '{input_file_path}' not found. Using built-in sample data to continue.")
    data = """time,hostId,accSendBytes,accAckedBytes
1000000000,105,100000,98000
1000000000,106,110000,105000
1000000000,107,105000,104000
1000000000,108,120000,118000
2000000000,105,250000,240000
2000000000,106,280000,260000
2000000000,107,260000,255000
2000000000,108,300000,290000
3000000000,105,380000,370000
3000000000,106,420000,400000
3000000000,107,390000,380000
3000000000,108,450000,435000
"""
    df = pd.read_csv(StringIO(data))

# === 3. 对所有数据计算速率 (提前计算) ===
# 按 hostId 和 time 排序，确保 diff() 计算正确
df.sort_values(by=['hostId', 'time'], inplace=True)

df['time_diff_s'] = df.groupby('hostId')['time'].diff() / 1e9
df['sent_diff'] = df.groupby('hostId')['accSendBytes'].diff()
df['acked_diff'] = df.groupby('hostId')['accAckedBytes'].diff()

df['throughput_rate'] = (df['sent_diff'] / df['time_diff_s']).fillna(0)
df['goodput_rate'] = (df['acked_diff'] / df['time_diff_s']).fillna(0)
df['unacked_rate'] = df['throughput_rate'] - df['goodput_rate']

# === 4. 选择要重点分析的主机 ===
all_hosts = sorted(df['hostId'].unique())
print(f"📊 Hosts found in the file: {all_hosts}")

num_to_select = min(4, len(all_hosts))
selected_hosts = all_hosts[:num_to_select]
print(f"✅ Selected hosts for detailed view: {selected_hosts}")

# 创建选中主机的数据副本
df_selected = df[df['hostId'].isin(selected_hosts)].copy()


# === CONDITIONAL BLOCK: Plotting vs. Statistics ===
if args.no_plot:
    # --- Mode: Calculate and Print Statistics ---
    print("\n📈 Calculating Average Rates (--no-plot specified)...")

    # --- 1. 计算选中主机的平均值 ---
    print("\n--- Average Rates for Selected Hosts ---")
    avg_throughput_selected = df_selected[df_selected['throughput_rate'] > 0].groupby('hostId')['throughput_rate'].mean()
    avg_goodput_selected = df_selected[df_selected['goodput_rate'] > 0].groupby('hostId')['goodput_rate'].mean()

    for host_id in selected_hosts:
        throughput_mbps = (avg_throughput_selected.get(host_id, 0) * 8) / 1e6
        goodput_mbps = (avg_goodput_selected.get(host_id, 0) * 8) / 1e6
        print(f"  Host ID {host_id}:")
        print(f"    - Average Throughput: {throughput_mbps:.2f} Mbps")
        print(f"    - Average Goodput:    {goodput_mbps:.2f} Mbps")
    print("----------------------------------------")

    # --- 2. 计算所有主机的总平均值 ---
    # 过滤掉所有主机数据中的初始零值
    valid_rates_all = df[df['throughput_rate'] > 0]
    
    # 直接在过滤后的整个数据集上求平均
    overall_avg_throughput = valid_rates_all['throughput_rate'].mean()
    overall_avg_goodput = valid_rates_all['goodput_rate'].mean()

    # 单位转换
    overall_throughput_mbps = (overall_avg_throughput * 8) / 1e6 if overall_avg_throughput else 0
    overall_goodput_mbps = (overall_avg_goodput * 8) / 1e6 if overall_avg_goodput else 0

    print("\n--- Overall Average (All Hosts) ---")
    print(f"  - Overall Average Throughput: {overall_throughput_mbps:.2f} Mbps")
    print(f"  - Overall Average Goodput:    {overall_goodput_mbps:.2f} Mbps")
    print("-----------------------------------\n")

else:
    # --- Mode: Plotting (Default Behavior) ---
    print("\n🎨 Generating plots...")
    
    # === 5. 平滑处理 ===
    window_size = 100
    df_selected['throughput_rate'] = df_selected['throughput_rate'].rolling(window=window_size).mean()
    df_selected['goodput_rate'] = df_selected['goodput_rate'].rolling(window=window_size).mean()

    output_prefix = file_id if file_id else "default"

    # === 6. 绘制速率图 ===
    num_hosts = len(selected_hosts)
    ncols = 2
    nrows = (num_hosts + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(14, nrows * 4), squeeze=False)
    axes = axes.flatten()

    for i, host_id in enumerate(selected_hosts):
        ax = axes[i]
        host_data = df_selected[df_selected['hostId'] == host_id]
        time_in_seconds = (host_data['time'] - host_data['time'].iloc[0]) / 1e9

        ax.plot(time_in_seconds, host_data['throughput_rate'] * 8e-6, label='Throughput Rate', linestyle='-')
        ax.plot(time_in_seconds, host_data['goodput_rate'] * 8e-6, label='Goodput Rate', linestyle='--')

        ax.set_title(f'Host ID: {host_id}')
        ax.set_xlabel('Time (seconds)')
        ax.set_ylabel('Rate (Mbps)')
        ax.grid(True)
        ax.legend()

    for i in range(num_hosts, len(axes)):
        fig.delaxes(axes[i])

    fig.suptitle('Throughput / Goodput Rate Over Time', fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    rate_filename = f'rate_over_time_{output_prefix}.png'
    plt.savefig(rate_filename)
    print(f"✅ Rate plot saved to '{rate_filename}'")

    # === 7. 绘制 Unacked 字节图 ===
    fig2, axes2 = plt.subplots(nrows=nrows, ncols=ncols, figsize=(14, nrows * 4), squeeze=False)
    axes2 = axes2.flatten()

    for i, host_id in enumerate(selected_hosts):
        ax = axes2[i]
        host_data = df_selected[df_selected['hostId'] == host_id]
        time_in_seconds = (host_data['time'] - host_data['time'].iloc[0]) / 1e9

        unacked_bytes = host_data['accSendBytes'] - host_data['accAckedBytes']
        unacked_bytes_smooth = unacked_bytes.rolling(window=window_size).mean()

        ax.plot(time_in_seconds, unacked_bytes_smooth, label='Unacked Bytes (Smoothed)', color='red')
        ax.set_title(f'Host ID: {host_id} - Unacked Bytes Over Time')
        ax.set_xlabel('Time (seconds)')
        ax.set_ylabel('Unacked Bytes')
        ax.grid(True)
        ax.legend()

    for i in range(num_hosts, len(axes2)):
        fig2.delaxes(axes2[i])

    fig2.suptitle('Unacked Bytes Over Time for Selected Hosts', fontsize=16)
    fig2.tight_layout(rect=[0, 0, 1, 0.96])
    unacked_filename = f'unacked_bytes_over_time_{output_prefix}.png'
    plt.savefig(unacked_filename)
    print(f"✅ Unacked bytes plot saved to '{unacked_filename}'")

    plt.show()