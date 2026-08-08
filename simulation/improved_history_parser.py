#!/usr/bin/env python3
"""
改进的历史记录解析器 - 支持完整的24字段格式
功能: 解析mix/.history文件，按实验参数分组整理，便于查找和分析
"""

import os
import re
import argparse
import json
from collections import defaultdict
from datetime import datetime

class HistoryParser:
    def __init__(self):
        # 完整的24字段格式 (基于run.py:495的格式)
        self.field_names = [
            'simulday',           # 0
            'config_ID',          # 1
            'cc_mode',           # 2
            'lb_mode',           # 3
            'ar_mode',           # 4
            'cwh_tx_expiry_time', # 5
            'cwh_extra_reply_deadline', # 6
            'cwh_path_pause_time', # 7
            'cwh_extra_voq_flush_time', # 8
            'cwh_default_voq_waiting_time', # 9
            'pfc',               # 10
            'irn',               # 11
            'has_win',           # 12
            'var_win',           # 13
            'window_size',       # 14
            'topo',              # 15
            'bw',                # 16
            'cdf',               # 17
            'load',              # 18
            'error_rate',        # 19
            'time',              # 20
            'timeout_slowstart_mode', # 21
            'irn_rto_high',      # 22
            'irn_rto_low'        # 23
        ]

    def parse_history_file(self, history_path="./mix/.history"):
        """解析history文件，返回实验记录列表"""
        experiments = []

        if not os.path.exists(history_path):
            print(f"History文件不存在: {history_path}")
            return experiments

        with open(history_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                # 跳过空行和命令行
                if not line or not ',' in line or line.startswith('./waf'):
                    continue

                fields = line.split(',')

                # 检查字段数量
                if len(fields) != len(self.field_names):
                    print(f"警告: 第{line_num}行字段数量不匹配 (期望{len(self.field_names)}, 实际{len(fields)})")
                    continue

                # 创建实验记录字典
                experiment = {}
                for i, field_name in enumerate(self.field_names):
                    experiment[field_name] = fields[i].strip()

                # 数据类型转换
                try:
                    experiment['load'] = int(experiment['load'])
                    experiment['error_rate'] = float(experiment['error_rate'])
                    experiment['pfc'] = int(experiment['pfc'])
                    experiment['irn'] = int(experiment['irn'])
                    experiment['window_size'] = int(experiment['window_size']) if experiment['window_size'] != '0' else 0
                    experiment['timeout_slowstart_mode'] = int(experiment['timeout_slowstart_mode'])
                    if experiment['irn_rto_high']:
                        experiment['irn_rto_high'] = int(experiment['irn_rto_high'])
                    if experiment['irn_rto_low']:
                        experiment['irn_rto_low'] = int(experiment['irn_rto_low'])
                except ValueError as e:
                    print(f"警告: 第{line_num}行数据转换错误: {e}")
                    continue

                # 添加派生字段
                experiment['line_number'] = line_num
                experiment['loss_type'] = 'lossless' if experiment['pfc'] == 1 else 'lossy'
                experiment['bandwidth'] = self._extract_bandwidth(experiment['topo'])
                experiment['topology_type'] = self._extract_topology_type(experiment['topo'])

                experiments.append(experiment)

        print(f"成功解析 {len(experiments)} 条实验记录")
        return experiments

    def _extract_bandwidth(self, topo):
        """从拓扑名提取带宽"""
        if '400G' in topo: return 400
        elif '200G' in topo: return 200
        else: return 100

    def _extract_topology_type(self, topo):
        """从拓扑名提取类型"""
        if 'fat' in topo: return 'fat_tree'
        elif 'leaf_spine' in topo: return 'leaf_spine'
        else: return 'unknown'

    def group_experiments(self, experiments, group_by=['topo', 'cdf', 'cc_mode', 'load', 'error_rate', 'loss_type']):
        """按指定字段分组实验"""
        groups = defaultdict(list)

        for exp in experiments:
            # 创建分组键
            key_parts = []
            for field in group_by:
                if field == 'loss_type':
                    key_parts.append(exp['loss_type'])
                else:
                    key_parts.append(str(exp.get(field, 'unknown')))

            group_key = '_'.join(key_parts)
            groups[group_key].append(exp)

        return dict(groups)

    def export_grouped_history(self, groups, output_dir="./mix/grouped_history"):
        """导出分组后的历史记录"""
        os.makedirs(output_dir, exist_ok=True)

        summary = {
            'total_groups': len(groups),
            'total_experiments': sum(len(experiments) for experiments in groups.values()),
            'groups': {}
        }

        for group_name, experiments in groups.items():
            # 为每个分组创建文件
            group_file = os.path.join(output_dir, f"{group_name}.txt")

            with open(group_file, 'w') as f:
                # 写入header
                f.write(','.join(self.field_names) + '\n')

                # 写入实验数据
                for exp in experiments:
                    row = [str(exp.get(field, '')) for field in self.field_names]
                    f.write(','.join(row) + '\n')

            # 统计信息
            lb_algorithms = set(exp['lb_mode'] for exp in experiments)
            summary['groups'][group_name] = {
                'experiment_count': len(experiments),
                'lb_algorithms': list(lb_algorithms),
                'config_ids': [exp['config_ID'] for exp in experiments]
            }

        # 写入汇总文件
        with open(os.path.join(output_dir, '_summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"分组完成: {len(groups)}个组，共{summary['total_experiments']}条记录")
        print(f"结果保存在: {output_dir}")

        return summary

    def search_experiments(self, experiments, **criteria):
        """搜索符合条件的实验"""
        results = []

        for exp in experiments:
            match = True
            for field, value in criteria.items():
                if field not in exp:
                    continue

                exp_value = exp[field]

                # 支持不同的匹配方式
                if isinstance(value, str):
                    if value.lower() not in str(exp_value).lower():
                        match = False
                        break
                elif isinstance(value, (int, float)):
                    if exp_value != value:
                        match = False
                        break
                elif isinstance(value, list):
                    if exp_value not in value:
                        match = False
                        break

            if match:
                results.append(exp)

        return results

    def print_experiment_summary(self, experiments):
        """打印实验汇总统计"""
        if not experiments:
            print("没有找到实验记录")
            return

        print(f"\n=== 实验汇总 (共 {len(experiments)} 条记录) ===")

        # 统计各种分布
        stats = {
            '拓扑': defaultdict(int),
            '带宽': defaultdict(int),
            'CDF': defaultdict(int),
            '拥塞控制': defaultdict(int),
            '负载均衡': defaultdict(int),
            '流控模式': defaultdict(int)
        }

        for exp in experiments:
            stats['拓扑'][exp.get('topo', 'unknown')] += 1
            stats['带宽'][f"{exp.get('bandwidth', 0)}G"] += 1
            stats['CDF'][exp.get('cdf', 'unknown')] += 1
            stats['拥塞控制'][exp.get('cc_mode', 'unknown')] += 1
            stats['负载均衡'][exp.get('lb_mode', 'unknown')] += 1
            stats['流控模式'][exp.get('loss_type', 'unknown')] += 1

        for category, counts in stats.items():
            print(f"\n{category}分布:")
            for item, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  {item}: {count}")

def main():
    parser = argparse.ArgumentParser(description="改进的历史记录解析和管理工具")
    parser.add_argument('action', choices=['parse', 'group', 'search', 'summary'],
                       help="执行的操作")
    parser.add_argument('--history', default='./mix/.history',
                       help="History文件路径")
    parser.add_argument('--output-dir', default='./mix/grouped_history',
                       help="输出目录")
    parser.add_argument('--group-by', nargs='+',
                       default=['topo', 'cdf', 'cc_mode', 'load', 'error_rate', 'loss_type'],
                       help="分组字段")

    # 搜索参数
    parser.add_argument('--topo', help="拓扑过滤")
    parser.add_argument('--cc', help="拥塞控制过滤")
    parser.add_argument('--lb', help="负载均衡过滤")
    parser.add_argument('--load', type=int, help="负载过滤")
    parser.add_argument('--bandwidth', type=int, help="带宽过滤")

    args = parser.parse_args()

    # 创建解析器
    history_parser = HistoryParser()

    # 解析历史记录
    experiments = history_parser.parse_history_file(args.history)

    if args.action == 'parse':
        print(f"解析完成，共 {len(experiments)} 条记录")

    elif args.action == 'summary':
        history_parser.print_experiment_summary(experiments)

    elif args.action == 'group':
        groups = history_parser.group_experiments(experiments, args.group_by)
        summary = history_parser.export_grouped_history(groups, args.output_dir)

    elif args.action == 'search':
        # 构建搜索条件
        criteria = {}
        if args.topo: criteria['topo'] = args.topo
        if args.cc: criteria['cc_mode'] = args.cc
        if args.lb: criteria['lb_mode'] = args.lb
        if args.load: criteria['load'] = args.load
        if args.bandwidth: criteria['bandwidth'] = args.bandwidth

        results = history_parser.search_experiments(experiments, **criteria)

        print(f"搜索结果: 找到 {len(results)} 条记录")
        for exp in results:
            print(f"ID: {exp['config_ID']}, 拓扑: {exp['topo']}, CC: {exp['cc_mode']}, "
                  f"LB: {exp['lb_mode']}, 负载: {exp['load']}")

if __name__ == "__main__":
    main()