#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandas as pd
import argparse
import os
import json
from collections import defaultdict

# --- 模式映射字典 (与参考脚本一致) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 7: "timely", 8: "dctcp",
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 6: "LetFlow", 9: "ConWeave",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -------------------------------------------------------------------

def get_spine_node_ids(n_leaf, n_spine, servers_per_leaf):
    """根据拓扑结构计算Spine交换机的节点ID范围"""
    n_servers_total = n_leaf * servers_per_leaf
    id_offset_leaf = n_servers_total
    id_offset_spine = id_offset_leaf + n_leaf
    spine_ids = list(range(id_offset_spine, id_offset_spine + n_spine))
    return spine_ids

def parse_qlen_file(filepath, spine_node_ids, queue_type_col):
    """
    (原始函数, 用于聚合的入口队列数据)
    读取队列长度文件, 筛选Spine节点, 并计算聚合后的统计信息。
    """
    column_names = [
        'timestamp', 'node_id', 'port_id', 'ingress_qlen', 
        'dynamic_threshold', 'egress_qlen'
    ]
    try:
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            print(f"警告: 队列长度文件为空: {filepath}。跳过。")
            return None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        print(f"警告: 队列长度文件未找到或为空: {filepath}。跳过。")
        return None
    except Exception as e:
        print(f"读取或解析文件 {filepath} 时出错: {e}")
        return None

    spine_df = df[df['node_id'].isin(spine_node_ids)]
    
    if spine_df.empty or queue_type_col not in spine_df.columns:
        return None
        
    # 1. 计算时间序列统计 (在所有Spine端口上聚合)
    time_stats = spine_df.groupby('timestamp')[queue_type_col].agg(['mean', 'max']).reset_index()
    
    # 2. 计算总体摘要统计 (聚合)
    summary = {
        'avg_qlen_bytes': float(spine_df[queue_type_col].mean()),
        'max_qlen_bytes': int(spine_df[queue_type_col].max()),
        'p99_qlen_bytes': float(spine_df[queue_type_col].quantile(0.99))
    }
    
    time_series_data = {
        'timestamps_ns': [int(ts) for ts in time_stats['timestamp']],
        'avg_qlen_bytes': [float(val) for val in time_stats['mean']],
        'max_qlen_bytes': [int(val) for val in time_stats['max']]
    }
    
    return {'time_series': time_series_data, 'summary': summary}

# --- 新增的核心函数：为每个端口单独解析出口队列长度 ---
def parse_egress_qlen_by_port(filepath, spine_node_ids):
    """
    读取队列长度文件，并为每一个独立的Spine端口计算出口队列的统计信息。
    
    返回:
        一个字典，其中每个键是 'spine_{node_id}_port_{port_id}' 字符串，
        值是该端口的统计数据字典。
    """
    column_names = [
        'timestamp', 'node_id', 'port_id', 'ingress_qlen', 
        'dynamic_threshold', 'egress_qlen'
    ]
    try:
        df = pd.read_csv(filepath, header=None, names=column_names)
        if df.empty:
            return None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None
    except Exception as e:
        print(f"读取或解析文件 {filepath} 时出错: {e}")
        return None

    spine_df = df[df['node_id'].isin(spine_node_ids)]
    if spine_df.empty:
        return None
    
    all_ports_data = {}
    
    # 核心：根据交换机ID和端口ID对数据进行分组，以实现对每个端口的独立处理
    grouped_by_port = spine_df.groupby(['node_id', 'port_id'])
    
    # 遍历每个分组（即每个独立的端口）
    for (node_id, port_id), port_df in grouped_by_port:
        if port_df.empty:
            continue
            
        # 确保数据按时间排序以生成正确的时间序列
        port_df = port_df.sort_values('timestamp')
        
        # 1. 为这个特定端口计算摘要统计
        summary = {
            'avg_qlen_bytes': float(port_df['egress_qlen'].mean()),
            'max_qlen_bytes': int(port_df['egress_qlen'].max()),
            'p99_qlen_bytes': float(port_df['egress_qlen'].quantile(0.99))
        }
        
        # 2. 准备这个特定端口的时间序列数据
        time_series_data = {
            'timestamps_ns': [int(ts) for ts in port_df['timestamp']],
            'qlen_bytes': [int(val) for val in port_df['egress_qlen']]
        }
        
        # 使用描述性的键来标识这个端口
        port_key = f"spine_{node_id}_port_{port_id}"
        all_ports_data[port_key] = {
            'summary': summary,
            'time_series': time_series_data
        }
        
    return all_ports_data if all_ports_data else None

def main():
    """主函数，用于解析参数、处理文件并生成JSON数据"""
    parser = argparse.ArgumentParser(description='解析Spine交换机队列长度并保存为结构化JSON文件。')
    parser.add_argument('history_file', type=str, help='包含模拟配置的历史文件的路径。')
    parser.add_argument('--n_leaf', type=int, default=8, help='拓扑中的Leaf交换机数量。')
    parser.add_argument('--n_spine', type=int, default=8, help='拓扑中的Spine交换机数量。')
    parser.add_argument('--servers_per_leaf', type=int, default=16, help='每个Leaf交换机连接的服务器数量。')
    
    args = parser.parse_args()

    file_dir = os.path.dirname(os.path.abspath(__file__))
    # 为了清晰，更改输出目录名称
    json_dir = os.path.join(file_dir, "json-data-spine-qlen-by-port")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    ns3_root_dir = os.path.abspath(os.path.join(file_dir, "..")) 
    output_data_dir = os.path.join(ns3_root_dir, "mix", "output")
    
    print(f"正在处理历史文件: {args.history_file}")
    
    map_key_to_config = defaultdict(list)

    # --- 步骤 1: 读取历史文件 (此处无更改) ---
    with open(args.history_file, "r") as f:
        for line in f.readlines():
            line = line.strip()
            if not line: continue
            
            try:
                parsed = line.split(',')
                if len(parsed) < 22: continue
                
                config_id = parsed[1]
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                topo = parsed[15]
                load_type = parsed[17]
                netload = parsed[18]
                error_rate = parsed[19]

                if (lb_mode_id not in lb_modes or irn not in irn_modes):
                    continue

                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "Ideal_Trimming"

                lb_mode_str = lb_modes.get(lb_mode_id)
                flow_control = "Lossless" if pfc == 1 else "Lossy"
                
                key = (topo, netload, flow_control, load_type, error_rate)
                
                entry_details = {
                    "config_id": config_id,
                    "lb_mode": lb_mode_str,
                    "recovery": recovery_label
                }
                map_key_to_config[key].append(entry_details)

            except (ValueError, IndexError) as e:
                print(f"警告: 无法解析行: '{line}'. 错误: {e}. 跳过。")
                continue

    # --- 步骤 2: 处理每个分组并生成JSON文件 ---
    spine_ids = get_spine_node_ids(args.n_leaf, args.n_spine, args.servers_per_leaf)
    print(f"已识别的Spine节点ID: {spine_ids}")

    for k, v_configs in map_key_to_config.items():
        qlen_group_data = {
            "metadata": {
                "topology": k[0],
                "network_load": k[1],
                "flow_control": k[2],
                "load_type": k[3],
                "error_rate": k[4],
            },
            "data_series": []
        }

        for entry in v_configs:
            config_id = entry["config_id"]
            qlen_file_path = os.path.join(output_data_dir, config_id, f"{config_id}_out_qlen.txt")
            
            print(f"---> 正在解析配置ID的数据: {config_id}")

            # --- 修改部分：调用新旧函数 ---
            # 获取聚合后的入口队列数据 (和以前一样)
            ingress_data = parse_qlen_file(qlen_file_path, spine_ids, 'ingress_qlen')
            # 使用新函数获取每个端口独立的出口队列数据
            egress_data_by_port = parse_egress_qlen_by_port(qlen_file_path, spine_ids)

            if ingress_data or egress_data_by_port:
                series_data = {
                    "load_balancing_mode": entry["lb_mode"],
                    "recovery_mechanism": entry["recovery"],
                    # 为了在最终JSON中更清晰，重命名键
                    "ingress_data_aggregated": ingress_data, 
                    "egress_data_by_port": egress_data_by_port
                }
                qlen_group_data["data_series"].append(series_data)
        
        if not qlen_group_data["data_series"]:
            print(f"因没有有效的队列长度数据，跳过分组 {k}。")
            continue
            
        # --- 步骤 3: 将收集的数据保存到JSON文件 ---
        json_filename = os.path.join(
            json_dir, 
            f"QLEN_DATA_TOPO_{k[0]}_LOAD_{k[1]}_FC_{k[2]}_TYPE_{k[3]}_ERR_{k[4]}.json"
        )
        print(f"正在保存QLen数据到: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(qlen_group_data, f, indent=4, ensure_ascii=False) # ensure_ascii=False 以正确显示中文
            
    print("\n✅ 所有文件解析成功！")

if __name__ == "__main__":
    main()