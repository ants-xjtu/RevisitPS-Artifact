#!/usr/bin/python3

import pandas as pd
import argparse
import os
import sys
import re
from collections import defaultdict

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

def format_table(df):
    """
    手动格式化DataFrame为对齐的表格
    """
    if df.empty:
        return ""

    # 获取列名和数据
    columns = df.columns.tolist()
    rows = df.values.tolist()

    # 计算每列的最大宽度
    col_widths = []
    for i, col in enumerate(columns):
        max_width = len(str(col))
        for row in rows:
            max_width = max(max_width, len(str(row[i])))
        col_widths.append(max_width)

    # 生成分隔线
    separator = "+" + "+".join(["-" * (w + 2) for w in col_widths]) + "+"

    # 格式化表头
    header = "|" + "|".join([f" {str(col):{col_widths[i]}} " for i, col in enumerate(columns)]) + "|"

    # 格式化数据行
    data_rows = []
    for row in rows:
        formatted_row = "|" + "|".join([f" {str(row[i]):{col_widths[i]}} " for i in range(len(row))]) + "|"
        data_rows.append(formatted_row)

    # 组合表格
    table = [separator, header, separator]
    table.extend(data_rows)
    table.append(separator)

    return "\n".join(table)

# --- Dictionaries for mode mapping (same as prase_dcn_fct.py) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5: "WAR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal", 4: "DCPAckOpt",
}

def parse_topology(topo_name):
    """
    从拓扑名称解析 n_leaf, n_spine, servers_per_leaf
    """
    # Leaf-Spine topology
    match = re.search(r'[Ll]eaf_?[Ss]pine_L(\d+)_S(\d+)', topo_name)
    if match:
        n_leaf = int(match.group(1))
        n_spine = int(match.group(2))
        servers_per_leaf = 16
        return {
            'type': 'leaf_spine',
            'n_leaf': n_leaf,
            'n_spine': n_spine,
            'servers_per_leaf': servers_per_leaf
        }

    # Fat-tree topology
    match = re.search(r'fat_k(\d+)', topo_name)
    if match:
        k = int(match.group(1))
        n_pods = k
        n_spine = k * k // 4
        n_leaf = k * k // 2
        servers_per_leaf = k // 2
        return {
            'type': 'fat_tree',
            'k': k,
            'n_leaf': n_leaf,
            'n_spine': n_spine,
            'servers_per_leaf': servers_per_leaf,
            'n_pods': n_pods
        }

    # Default fallback
    return {
        'type': 'unknown',
        'n_leaf': 8,
        'n_spine': 16,
        'servers_per_leaf': 16
    }

def process_pfc_log(filepath):
    """
    解析PFC日志文件，为每个端口提取暂停时间间隔。
    """
    try:
        column_names = ['TimeStep', 'NodeID', 'NodeType', 'IfIndex', 'PfcType']
        df = pd.read_csv(filepath, sep=' ', header=None, names=column_names,
                         dtype={'TimeStep': 'uint64', 'NodeID': 'uint32', 'NodeType': 'uint32',
                                'IfIndex': 'uint32', 'PfcType': 'uint32'})
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return None

    if df.empty:
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

        if last_pause_start is not None:
            intervals.append({
                'NodeID': node_id,
                'IfIndex': if_index,
                'StartTime': last_pause_start,
                'EndTime': sim_end_time
            })
    return intervals

def classify_port_type(node_id, if_index, topo_params):
    """
    根据拓扑参数分类端口类型，返回端口类型和目标Leaf ID (如果是Spine-to-Leaf)
    """
    n_leaf = topo_params['n_leaf']
    n_spine = topo_params['n_spine']
    servers_per_leaf = topo_params['servers_per_leaf']

    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf

    # Leaf switch ports
    if id_offset_leaf <= node_id < id_offset_spine:
        if if_index <= servers_per_leaf:
            return 'Leaf-to-Server', None
        else:
            return 'Leaf-to-Spine', None

    # Spine switch ports
    elif id_offset_spine <= node_id < id_offset_spine + n_spine:
        # if_index - 1 是目标 Leaf 的索引
        target_leaf_id = if_index - 1
        return 'Spine-to-Leaf', target_leaf_id

    return 'Unknown', None

def analyze_pfc_detailed(intervals, topo_params):
    """
    详细分析PFC暂停数据，按端口类型和目标Leaf分组
    """
    if not intervals:
        return None

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']

    # 添加端口类型分类和目标Leaf ID
    df[['PortType', 'TargetLeafID']] = df.apply(
        lambda row: pd.Series(classify_port_type(row['NodeID'], row['IfIndex'], topo_params)),
        axis=1
    )

    # 计算每个端口的总暂停时间
    port_stats = df.groupby(['NodeID', 'IfIndex', 'PortType', 'TargetLeafID']).agg({
        'Duration': ['sum', 'count', 'mean', 'std', 'min', 'max']
    }).reset_index()

    port_stats.columns = ['NodeID', 'IfIndex', 'PortType', 'TargetLeafID',
                          'TotalPause', 'PauseCount', 'AvgPause', 'StdPause', 'MinPause', 'MaxPause']

    results = {
        'port_stats': port_stats,
        'summary_by_type': {},
        'spine_to_leaf_by_target': {}
    }

    # 按端口类型汇总
    for port_type in ['Leaf-to-Server', 'Leaf-to-Spine', 'Spine-to-Leaf']:
        ports = port_stats[port_stats['PortType'] == port_type]

        if not ports.empty:
            total_pause_per_port = ports['TotalPause']
            results['summary_by_type'][port_type] = {
                'port_count': len(ports),
                'total_pause_all': total_pause_per_port.sum(),
                'avg_pause_per_port': total_pause_per_port.mean(),
                'std_pause_per_port': total_pause_per_port.std(),
                'cv_across_ports': total_pause_per_port.std() / total_pause_per_port.mean() if total_pause_per_port.mean() > 0 else 0,
                'min_pause_per_port': total_pause_per_port.min(),
                'max_pause_per_port': total_pause_per_port.max()
            }

    # Spine-to-Leaf 按目标Leaf分组分析
    spine_to_leaf_ports = port_stats[port_stats['PortType'] == 'Spine-to-Leaf']

    if not spine_to_leaf_ports.empty:
        n_leaf = topo_params['n_leaf']

        for leaf_id in range(n_leaf):
            leaf_ports = spine_to_leaf_ports[spine_to_leaf_ports['TargetLeafID'] == leaf_id]

            if not leaf_ports.empty:
                total_pause_per_port = leaf_ports['TotalPause']
                results['spine_to_leaf_by_target'][leaf_id] = {
                    'port_count': len(leaf_ports),
                    'total_pause_all': total_pause_per_port.sum(),
                    'avg_pause_per_port': total_pause_per_port.mean(),
                    'std_pause_per_port': total_pause_per_port.std(),
                    'cv': total_pause_per_port.std() / total_pause_per_port.mean() if total_pause_per_port.mean() > 0 else 0,
                    'min_pause_per_port': total_pause_per_port.min(),
                    'max_pause_per_port': total_pause_per_port.max()
                }

    return results

def print_experiment_analysis(config_info, analysis_results, topo_params):
    """
    打印单个实验的详细分析
    """
    print("\n" + "="*120)
    print(f"实验配置 ID: {config_info['config_id']}")
    print("="*120)

    print(f"  拓扑:         {config_info['topology']} (Leaf={topo_params['n_leaf']}, Spine={topo_params['n_spine']})")
    print(f"  负载:         {config_info['netload']}%")
    print(f"  流控:         {config_info['flow_control']}")
    print(f"  负载均衡:     {config_info['lb']}")
    print(f"  拥塞控制:     {config_info['cc']}")
    print(f"  恢复机制:     {config_info['recovery']}")
    print(f"  缓冲区:       {config_info['buffer_mb']} MB")
    print(f"  流量模式:     {config_info['cdf']}")

    summary = analysis_results['summary_by_type']

    print("\n" + "-"*120)
    print("端口类型统计:")
    print("-"*120)

    for port_type in ['Leaf-to-Server', 'Leaf-to-Spine', 'Spine-to-Leaf']:
        if port_type in summary:
            s = summary[port_type]
            print(f"\n  [{port_type}]")
            print(f"    端口数量:           {s['port_count']}")
            print(f"    总暂停时间:         {s['total_pause_all']:,} ns")
            print(f"    平均暂停/端口:      {s['avg_pause_per_port']:,.2f} ns")
            print(f"    标准差:             {s['std_pause_per_port']:,.2f} ns")
            print(f"    变异系数 (CV):      {s['cv_across_ports']:.4f}")
            print(f"    最小/最大:          {s['min_pause_per_port']:,} / {s['max_pause_per_port']:,} ns")

    # Spine-to-Leaf 详细分析
    spine_by_target = analysis_results['spine_to_leaf_by_target']

    if spine_by_target:
        print("\n" + "-"*120)
        print("⭐ Spine-to-Leaf 按目标Leaf分组分析:")
        print("-"*120)

        # 创建表格数据
        leaf_table = []
        for leaf_id in sorted(spine_by_target.keys()):
            s = spine_by_target[leaf_id]
            leaf_table.append({
                'Leaf ID': leaf_id,
                'Spine端口数': s['port_count'],
                '总暂停时间(ns)': f"{s['total_pause_all']:,}",
                '平均暂停/端口(ns)': f"{s['avg_pause_per_port']:,.2f}",
                '标准差(ns)': f"{s['std_pause_per_port']:,.2f}",
                '变异系数': f"{s['cv']:.4f}",
                '最小(ns)': f"{s['min_pause_per_port']:,}",
                '最大(ns)': f"{s['max_pause_per_port']:,}"
            })

        df_leaf = pd.DataFrame(leaf_table)

        if HAS_TABULATE:
            print(tabulate(df_leaf, headers='keys', tablefmt='grid', showindex=False))
        else:
            print(format_table(df_leaf))

        # 计算各Leaf组的CV
        cv_values = [spine_by_target[lid]['cv'] for lid in sorted(spine_by_target.keys())]
        avg_pause_values = [spine_by_target[lid]['avg_pause_per_port'] for lid in sorted(spine_by_target.keys())]

        print(f"\n  Leaf组综合分析:")
        print(f"    各Leaf组的CV范围:    {min(cv_values):.4f} ~ {max(cv_values):.4f}")
        print(f"    各Leaf组的平均CV:    {sum(cv_values)/len(cv_values):.4f}  {'✓ 均衡' if sum(cv_values)/len(cv_values) < 0.2 else '✗ 不均衡'}")
        print(f"    各Leaf平均暂停范围:  {min(avg_pause_values):,.2f} ~ {max(avg_pause_values):,.2f} ns")

def main():
    parser = argparse.ArgumentParser(description='Parse multiple PFC logs with detailed per-experiment analysis.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    parser.add_argument('-o', '--output', type=str, default=None, help='Output CSV file path (optional)')
    parser.add_argument('--summary-only', action='store_true', help='Only show summary, skip per-experiment details')
    args = parser.parse_args()

    file_dir = os.path.dirname(os.path.realpath(__file__))
    output_dir = os.path.join(file_dir, "../mix/output")
    history_filename = args.history_file

    print(f"Processing history file: {history_filename}\n")

    # Store results for summary
    all_results = []

    with open(history_filename, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line:
                continue

            parsed = line.split(',')
            if len(parsed) < 22:
                continue

            try:
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                irn = int(parsed[11])

                if (cc_mode_id not in cc_modes or
                    lb_mode_id not in lb_modes or
                    irn not in irn_modes):
                    continue

                config_id = parsed[1]
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                window_size = parsed[14]
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]
                timeout_mode = parsed[21]
                buffer_size = parsed[7] if len(parsed) > 7 else "N/A"

                # Build recovery label
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "IdealTrimming"

                if timeout_mode == '1':
                    if recovery_label == "RTO+GBN":
                        recovery_label = "RTO+GBN+slowstart"
                    elif recovery_label == "IdealTrimming":
                        recovery_label = "IdealTrimming+slowstart"
                    elif recovery_label == "Ideal":
                        recovery_label = "Ideal+slowstart"
                elif timeout_mode == '2':
                    if recovery_label == "RTO+GBN":
                        recovery_label = f"RTO+GBN+Now"

                lb_mode_str = lb_modes.get(lb_mode_id)
                cc_mode_str = cc_modes.get(cc_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"

                # Parse topology parameters
                topo_params = parse_topology(topo)

                # Find PFC file
                pfc_file = f"{output_dir}/{config_id}/{config_id}_out_pfc.txt"

                if os.path.exists(pfc_file):
                    intervals = process_pfc_log(pfc_file)
                    if intervals is not None and len(intervals) > 0:
                        analysis_results = analyze_pfc_detailed(intervals, topo_params)

                        if analysis_results:
                            config_info = {
                                'config_id': config_id,
                                'topology': topo,
                                'netload': netload,
                                'flow_control': flow_control,
                                'cdf': load_type,
                                'error_rate': error_rate,
                                'cc': cc_mode_str,
                                'lb': lb_mode_str,
                                'recovery': recovery_label,
                                'buffer_mb': buffer_size
                            }

                            # Print per-experiment analysis
                            if not args.summary_only:
                                print_experiment_analysis(config_info, analysis_results, topo_params)

                            # Store for summary
                            all_results.append({
                                'config_info': config_info,
                                'analysis': analysis_results,
                                'topo_params': topo_params
                            })

            except (ValueError, IndexError) as e:
                continue

    if not all_results:
        print("\nNo valid PFC data found!")
        return

    # Print summary comparison
    print("\n\n" + "="*120)
    print("汇总对比: Spine-to-Leaf 端口 PFC 暂停统计")
    print("="*120)

    summary_table = []
    for result in all_results:
        config = result['config_info']
        analysis = result['analysis']

        if 'Spine-to-Leaf' in analysis['summary_by_type']:
            s = analysis['summary_by_type']['Spine-to-Leaf']

            # Calculate leaf-level CV statistics
            spine_by_target = analysis['spine_to_leaf_by_target']
            if spine_by_target:
                cv_values = [spine_by_target[lid]['cv'] for lid in spine_by_target.keys()]
                avg_pause_values = [spine_by_target[lid]['avg_pause_per_port'] for lid in spine_by_target.keys()]

                # 各Leaf组的平均CV（所有Leaf组CV之和 / 组数）
                avg_cv_across_leaves = sum(cv_values) / len(cv_values)
                cv_range = f"{min(cv_values):.4f}-{max(cv_values):.4f}"
            else:
                avg_cv_across_leaves = 0
                cv_range = "N/A"

            summary_table.append({
                'config_id': config['config_id'],
                'topo': config['topology'][:25],
                'load%': config['netload'],
                'lb': config['lb'],
                'cc': config['cc'],
                'buf_mb': config['buffer_mb'],
                '总暂停(ns)': f"{s['total_pause_all']:,.0f}",
                '平均暂停/端口(ns)': f"{s['avg_pause_per_port']:,.0f}",
                '所有端口CV': f"{s['cv_across_ports']:.4f}",
                '各Leaf组CV范围': cv_range,
                '各Leaf组平均CV': f"{avg_cv_across_leaves:.4f}"
            })

    df_summary = pd.DataFrame(summary_table)

    if HAS_TABULATE:
        print(tabulate(df_summary, headers='keys', tablefmt='grid', showindex=False))
    else:
        print(format_table(df_summary))

    # Save to CSV if specified
    if args.output:
        df_summary.to_csv(args.output, index=False)
        print(f"\n✓ Summary saved to: {args.output}")

    # Final insights
    print("\n" + "="*120)
    print("关键发现:")
    print("="*120)

    df_summary['所有端口CV_num'] = df_summary['所有端口CV'].astype(float)
    df_summary['各Leaf组平均CV_num'] = df_summary['各Leaf组平均CV'].astype(float)

    best_all_port_cv = df_summary.loc[df_summary['所有端口CV_num'].idxmin()]
    best_leaf_avg_cv = df_summary.loc[df_summary['各Leaf组平均CV_num'].idxmin()]

    print(f"  所有Spine端口最均衡:  {best_all_port_cv['lb']} (所有端口CV={best_all_port_cv['所有端口CV']}, config_id={best_all_port_cv['config_id']})")
    print(f"  各Leaf组最均衡:       {best_leaf_avg_cv['lb']} (各Leaf组平均CV={best_leaf_avg_cv['各Leaf组平均CV']}, config_id={best_leaf_avg_cv['config_id']})")

if __name__ == "__main__":
    main()
