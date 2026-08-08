#!/usr/bin/python3

import pandas as pd
import matplotlib.pyplot as plt
import argparse
import os
import numpy as np

# ... (process_pfc_log, calculate_and_print_pause_stats, calculate_detailed_pause_stats, calculate_per_leaf_stats 函數保持不變) ...
def process_pfc_log(filepath):
    """
    解析PFC日志文件，为每个端口提取暂停时间间隔。
    """
    try:
        column_names = ['TimeStep', 'NodeID', 'NodeType', 'IfIndex', 'PfcType']
        df = pd.read_csv(filepath, sep=' ', header=None, names=column_names,
                         dtype={'TimeStep': 'uint64', 'NodeID': 'uint32', 'NodeType': 'uint32', 'IfIndex': 'uint32', 'PfcType': 'uint32'})
    except FileNotFoundError:
        print(f"错误: 文件未找到 '{filepath}'")
        return None
    except Exception as e:
        print(f"读取或解析文件时发生错误: {e}")
        return None

    if df.empty:
        print("警告: 日志文件为空或格式不正确。")
        return []

    df.sort_values(by='TimeStep', inplace=True)
    sim_end_time = df['TimeStep'].max()

    intervals = []
    grouped = df.groupby(['NodeID', 'IfIndex'])

    for (node_id, if_index), group_df in grouped:
        last_pause_start = None
        for _, row in group_df.iterrows():
            if row['PfcType'] == 1:
                if last_pause_start is None:
                    last_pause_start = row['TimeStep']
            elif row['PfcType'] == 0:
                if last_pause_start is not None:
                    intervals.append({
                        'NodeID': node_id,
                        'IfIndex': if_index,
                        'StartTime': last_pause_start,
                        'EndTime': row['TimeStep']
                    })
                    last_pause_start = None
                else:
                    print(f"警告: 在时间 {row['TimeStep']} 节点 {node_id}-端口 {if_index} 收到恢复信号，但没有找到对应的暂停事件。")

        if last_pause_start is not None:
            intervals.append({
                'NodeID': node_id,
                'IfIndex': if_index,
                'StartTime': last_pause_start,
                'EndTime': sim_end_time
            })
    return intervals

def calculate_and_print_pause_stats(intervals, time_unit='ns'):
    """
    计算每个端口的总暂停时间、暂停次数，并打印统计数据。
    """
    if not intervals:
        print("没有可供统计的暂停数据。")
        return
    stats_df = pd.DataFrame(intervals)
    stats_df['Duration'] = stats_df['EndTime'] - stats_df['StartTime']
    port_stats = stats_df.groupby(['NodeID', 'IfIndex']).agg(
        TotalPauseDuration=('Duration', 'sum'),
        PauseCount=('Duration', 'size')
    ).reset_index()
    port_stats.sort_values(by='TotalPauseDuration', ascending=False, inplace=True)
    port_stats.rename(columns={'TotalPauseDuration': f'TotalPauseDuration ({time_unit})'}, inplace=True)
    print("\n--- 每个端口的PFC暂停统计 ---")
    print(port_stats.to_string(index=False))
    print("---------------------------------\n")

def calculate_detailed_pause_stats(intervals, time_unit='ns', n_leaf=8, n_spine=16, servers_per_leaf=16):
    """
    计算并打印 Leaf-Spine 拓扑中不同端口类型的详细暂停统计信息。
    """
    if not intervals:
        print("没有可供分析的详细暂停数据。")
        return

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf

    def get_port_type(row):
        node_id = row['NodeID']
        if_index = row['IfIndex']
        if id_offset_leaf <= node_id < id_offset_spine:
            if if_index <= servers_per_leaf: return 'Leaf-to-Server'
            else: return 'Leaf-to-Spine'
        elif id_offset_spine <= node_id < id_offset_spine + n_spine:
            return 'Spine-to-Leaf'
        else: return 'Unknown'
    df['PortType'] = df.apply(get_port_type, axis=1)

    print("\n--- [整体] 按端口类型的详细暂停时长分析 ---")
    port_total_pause = df.groupby(['NodeID', 'IfIndex', 'PortType'])['Duration'].sum().reset_index()
    
    leaf_to_spine_ports = port_total_pause[port_total_pause['PortType'] == 'Leaf-to-Spine']
    if not leaf_to_spine_ports.empty:
        avg_pause = leaf_to_spine_ports['Duration'].mean()
        min_pause = leaf_to_spine_ports['Duration'].min()
        max_pause = leaf_to_spine_ports['Duration'].max()
        print(f"\nLeaf 上行端口 (Leaf-to-Spine):")
        print(f"  - 平均暂停时长: {avg_pause:.2f} {time_unit}")
        print(f"  - 最短暂停时长: {min_pause} {time_unit}")
        print(f"  - 最长暂停时长: {max_pause} {time_unit}")
    else:
        print("\n未找到 Leaf-to-Spine 端口的暂停数据。")

    spine_to_leaf_ports = port_total_pause[port_total_pause['PortType'] == 'Spine-to-Leaf']
    if not spine_to_leaf_ports.empty:
        avg_pause = spine_to_leaf_ports['Duration'].mean()
        min_pause = spine_to_leaf_ports['Duration'].min()
        max_pause = spine_to_leaf_ports['Duration'].max()
        print(f"\nSpine 下行端口 (Spine-to-Leaf):")
        print(f"  - 平均暂停时长: {avg_pause:.2f} {time_unit}")
        print(f"  - 最短暂停时长: {min_pause} {time_unit}")
        print(f"  - 最长暂停时长: {max_pause} {time_unit}")
    else:
        print("\n未找到 Spine-to-Leaf 端口的暂停数据。")
    print("----------------------------------------\n")

def calculate_per_leaf_stats(intervals, time_unit='ns', n_leaf=8, n_spine=16, servers_per_leaf=16):
    """
    按每个Leaf为单位，分别统计其上行和下行链路的暂停情况。
    """
    if not intervals:
        return

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']
    
    # --- 拓扑参数 ---
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf

    def get_port_type(row):
        node_id = row['NodeID']
        if_index = row['IfIndex']
        if id_offset_leaf <= node_id < id_offset_spine:
            return 'Leaf-to-Spine' if if_index > servers_per_leaf else 'Leaf-to-Server'
        elif id_offset_spine <= node_id < id_offset_spine + n_spine:
            return 'Spine-to-Leaf'
        return 'Unknown'
    df['PortType'] = df.apply(get_port_type, axis=1)

    # 计算每个端口的总暂停时间
    port_total_pause = df.groupby(['NodeID', 'IfIndex', 'PortType'])['Duration'].sum().reset_index()

    print("\n--- [精细] 按每个Leaf分组的暂停时长分析 ---")

    # --- 1. Leaf-to-Spine (上行) 统计, 按源Leaf分组 ---
    print("\nLeaf 上行端口 (Leaf -> Spine):")
    leaf_to_spine_ports = port_total_pause[port_total_pause['PortType'] == 'Leaf-to-Spine']
    if not leaf_to_spine_ports.empty:
        # 按 NodeID (即Leaf的ID) 分组
        grouped_by_leaf = leaf_to_spine_ports.groupby('NodeID')['Duration']
        
        for node_id, durations in grouped_by_leaf:
            leaf_idx = node_id - id_offset_leaf
            stats = durations.agg(['mean', 'min', 'max'])
            print(f"  - 源 Leaf {int(leaf_idx)} (NodeID {node_id}):")
            print(f"    - 平均暂停: {stats['mean']:.2f} {time_unit}")
            print(f"    - 最短暂停: {stats['min']} {time_unit}")
            print(f"    - 最长暂停: {stats['max']} {time_unit}")
    else:
        print("  - 未找到 Leaf-to-Spine 端口的暂停数据。")

    # --- 2. Spine-to-Leaf (下行) 统计, 按目标Leaf分组 ---
    print("\nSpine 下行端口 (Spine -> Leaf):")
    spine_to_leaf_ports = port_total_pause[port_total_pause['PortType'] == 'Spine-to-Leaf']
    if not spine_to_leaf_ports.empty:
        # 关键假设: Spine上的端口索引 `IfIndex` 减 1 对应目标 Leaf 的索引
        # 例如: Spine的端口1 -> Leaf 0, 端口2 -> Leaf 1, ...
        spine_to_leaf_ports['TargetLeafIndex'] = spine_to_leaf_ports['IfIndex'] - 1

        # 按推断出的目标Leaf索引进行分组
        grouped_by_target_leaf = spine_to_leaf_ports.groupby('TargetLeafIndex')['Duration']
        
        for leaf_idx, durations in grouped_by_target_leaf:
            if 0 <= leaf_idx < n_leaf:
                stats = durations.agg(['mean', 'min', 'max'])
                print(f"  - 目标 Leaf {int(leaf_idx)}:")
                print(f"    - 平均暂停: {stats['mean']:.2f} {time_unit}")
                print(f"    - 最短暂停: {stats['min']} {time_unit}")
                print(f"    - 最长暂停: {stats['max']} {time_unit}")
    else:
        print("  - 未找到 Spine-to-Leaf 端口的暂停数据。")
        
    print("------------------------------------------\n")

# ===============================================================
# 更新后的函数
# ===============================================================
def calculate_spine_port_variance_per_leaf(intervals, time_unit='ns', n_leaf=8, n_spine=16, servers_per_leaf=16):
    """
    按目标 Leaf 分组，统计所有连接到该 Leaf 的 Spine 端口的暂停时长，
    并计算最大、最小、极差、方差、标准差和变异系数。
    """
    if not intervals:
        print("没有可供分析的数据。")
        return

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']
    
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf

    # 仅关注 Spine 节点
    spine_nodes = df[df['NodeID'] >= id_offset_spine]
    # 计算每个端口的总暂停
    port_total_pause = spine_nodes.groupby(['NodeID', 'IfIndex'])['Duration'].sum().reset_index()

    # 关键假设: Spine 上的端口索引 `IfIndex` 减 1 对应目标 Leaf 的索引
    port_total_pause['TargetLeafIndex'] = port_total_pause['IfIndex'] - 1
    
    # 筛选出有效的、指向 Leaf 的端口
    spine_to_leaf_ports = port_total_pause[
        (port_total_pause['TargetLeafIndex'] >= 0) & 
        (port_total_pause['TargetLeafIndex'] < n_leaf)
    ]

    if spine_to_leaf_ports.empty:
        print("\n--- [精细均衡分析] 未找到任何 Spine-to-Leaf 端口的暂停数据 ---\n")
        return
        
    print("\n--- [精细均衡分析] 按目标Leaf统计的Spine各端口暂停分布 ---")
    
    # 按目标 Leaf 索引进行分组
    grouped_by_target_leaf = spine_to_leaf_ports.groupby('TargetLeafIndex')
    
    for leaf_idx, group_df in grouped_by_target_leaf:
        print(f"\n--- 目标 Leaf {int(leaf_idx)} ---")
        
        # 1. 打印每个源 Spine 端口的暂停时长
        print("  各Spine源端口的暂停时长:")
        # .sort_values('NodeID') 确保每次输出Spine顺序一致
        for _, row in group_df.sort_values('NodeID').iterrows():
            spine_id = row['NodeID']
            duration = row['Duration']
            print(f"    - Spine Node {spine_id}: {duration} {time_unit}")

        # 2. 计算并打印统计摘要
        durations = group_df['Duration']
        max_val = durations.max()
        min_val = durations.min()
        
        # 如果只有一个数据点或所有数据都相同，则波动性指标为0
        if len(durations) > 1 and max_val != min_val:
            mean_val = durations.mean()
            range_val = max_val - min_val
            # ddof=0 计算总体方差/标准差，而不是样本的。这更符合我们的场景（观察所有Spine）
            variance_val = durations.var(ddof=0)
            std_dev_val = durations.std(ddof=0)
            # 避免除以0的错误
            cv_val = (std_dev_val / mean_val) if mean_val > 0 else 0.0
        else:
            mean_val = durations.mean() # 仍然计算平均值
            range_val = 0
            variance_val = 0
            std_dev_val = 0
            cv_val = 0

        print("\n  统计摘要:")
        print(f"    - 平均值 (Mean): {mean_val:.2f} {time_unit}")
        print(f"    - 最长暂停 (Max): {max_val} {time_unit}")
        print(f"    - 最短暂停 (Min): {min_val} {time_unit}")
        print(f"    - 极差 (Range): {range_val} {time_unit}")
        print(f"    - 暂停时长方差 (Variance): {variance_val:.2f} {time_unit}²")
        print(f"    - 暂停时长标准差 (Std Dev): {std_dev_val:.2f} {time_unit}")
        print(f"    - 变异系数 (CV): {cv_val:.4f}")
        
    print("----------------------------------------------------\n")


# ... (generate_simplified_pfc_group, plot_pause_timeline 函數保持不變) ...
def generate_simplified_pfc_group(n_leaf, n_spine, servers_per_leaf, source_leaf_idx, target_leaf_indices):
    group_ports = set()
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf
    source_leaf_id = id_offset_leaf + source_leaf_idx
    server_port_on_source_leaf = (source_leaf_id, 1)
    group_ports.add(server_port_on_source_leaf)
    port_on_spine_from_source_leaf = source_leaf_idx + 1
    for k in range(n_spine):
        spine_id = id_offset_spine + k
        group_ports.add((spine_id, port_on_spine_from_source_leaf))
    for target_idx in target_leaf_indices:
        target_leaf_id = id_offset_leaf + target_idx
        for k in range(n_spine):
            port_on_leaf_from_spine_k = servers_per_leaf + k + 1
            group_ports.add((target_leaf_id, port_on_leaf_from_spine_k))
    return group_ports

def plot_pause_timeline(intervals, output_file, time_unit='ns'):
    if not intervals:
        print("没有找到任何完整的暂停时间段，无法生成图像。")
        return
    plot_df = pd.DataFrame(intervals)
    plot_df['PortLabel'] = plot_df.apply(lambda row: f"Node {row['NodeID']}-Port {row['IfIndex']}", axis=1)
    n_leaf, n_spine, servers_per_leaf = 8, 16, 16
    source_leaf, target_leafs = 0, [2, 4]
    print(f"为特定路径生成端口分组: Leaf {source_leaf} -> Leafs {target_leafs}...")
    target_group = generate_simplified_pfc_group(n_leaf, n_spine, servers_per_leaf, source_leaf, target_leafs)
    filtered_df = plot_df[plot_df.apply(lambda row: (row['NodeID'], row['IfIndex']) in target_group, axis=1)]
    if filtered_df.empty:
        print("警告: 日志文件中没有找到与指定传播路径相关的暂停事件，无法生成图像。")
        return
    ordered_labels = sorted(filtered_df['PortLabel'].unique())
    y_pos_map = {label: i for i, label in enumerate(ordered_labels)}
    fig_height = max(6, len(ordered_labels) * 0.5)
    fig, ax = plt.subplots(figsize=(15, fig_height))
    for _, row in filtered_df.iterrows():
        y, start, duration = y_pos_map[row['PortLabel']], row['StartTime'], row['EndTime'] - row['StartTime']
        ax.barh(y, duration, left=start, height=0.6, color='darkorange', alpha=0.8, label='Paused')
    ax.set_yticks(range(len(ordered_labels)))
    ax.set_yticklabels(ordered_labels)
    ax.set_xlabel(f"Time ({time_unit})")
    ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0), useMathText=True)
    title = f"PFC Pause Timeline: Propagation from Leaf {source_leaf} to Leafs {target_leafs}"
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Node and Port Interface")
    ax.grid(True, axis='x', linestyle='--', alpha=0.6)
    handles, labels = plt.gca().get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label: ax.legend(by_label.values(), by_label.keys())
    plt.tight_layout()
    try:
        plt.savefig(output_file, bbox_inches='tight', dpi=300)
        print(f"图像已成功保存至: {output_file}")
    except Exception as e:
        print(f"保存图像时发生错误: {e}")
    plt.close()

def main():
    """
    主函数，处理命令行参数并调用处理和绘图函数。
    """
    parser = argparse.ArgumentParser(description="""
        分析并可视化PFC（Priority Flow Control）暂停/恢复日志。
    """)
    parser.add_argument("input", help="输入的PFC日志文件路径。")
    parser.add_argument("-o", "--output", default="pfc_timeline_simplified_path.pdf",
                        help="输出的图像文件路径 (例如: pfc.pdf, pfc.png)。默认: pfc_timeline_simplified_path.pdf")
    parser.add_argument("-u", "--unit", default="ns",
                        help="时间单位 (例如: ns, us)。默认: ns")
    parser.add_argument("--plot", action="store_true",
                        help="启用此标志以生成并保存PFC时间线图。")
    args = parser.parse_args()

    if args.plot:
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"已创建输出目录: {output_dir}")

    print("开始处理日志文件...")
    pfc_intervals = process_pfc_log(args.input)

    if pfc_intervals is not None:
        print(f"处理完成，共找到 {len(pfc_intervals)} 个暂停时间段。")
        
        # 定义拓扑结构，方便复用
        topo_params = {'n_leaf': 8, 'n_spine': 16, 'servers_per_leaf': 16}

        # 1. 原始的每个端口的详细统计
        calculate_and_print_pause_stats(pfc_intervals, args.unit)
        
        # 2. 原始的整体统计
        calculate_detailed_pause_stats(pfc_intervals, args.unit, **topo_params)

        # 3. 按每个Leaf分组的精细统计
        calculate_per_leaf_stats(pfc_intervals, args.unit, **topo_params)

        # 4. 按目标Leaf统计Spine端口暂停分布的函数
        calculate_spine_port_variance_per_leaf(pfc_intervals, args.unit, **topo_params)

        if args.plot:
            print("开始生成图像...")
            plot_pause_timeline(pfc_intervals, args.output, args.unit)

if __name__ == "__main__":
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams['font.family'] = 'sans-serif'
    # 使用支持中文的字体，例如 SimHei
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'SimHei'] 
    plt.rcParams['axes.unicode_minus'] = False
    # 修正之前的拼写错误
    plt.rcParams['figure.autolayout'] = True
    main()