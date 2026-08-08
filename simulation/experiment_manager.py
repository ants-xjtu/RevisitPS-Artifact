#!/usr/bin/env python3
"""
实验历史记录管理工具
功能: 整理autorun脚本产生的日志文件，提供结构化查询和管理
"""

import os
import json
import sqlite3
import re
import csv
import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd

class ExperimentManager:
    def __init__(self, base_dir="."):
        self.base_dir = Path(base_dir)
        self.logs_dir = self.base_dir / "logs"
        self.db_path = self.base_dir / "experiments.db"
        self.init_database()

    def init_database(self):
        """初始化SQLite数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            topology TEXT NOT NULL,
            netload INTEGER NOT NULL,
            error_rate REAL NOT NULL,
            cdf TEXT NOT NULL,
            cc TEXT NOT NULL,
            pfc INTEGER NOT NULL,
            irn INTEGER NOT NULL,
            armode TEXT NOT NULL,
            timeout_mode INTEGER NOT NULL,
            win_size INTEGER NOT NULL,
            rto_high INTEGER,
            rto_low INTEGER,
            buffer_size INTEGER,
            bandwidth INTEGER,
            lb_algorithm TEXT NOT NULL,
            log_file TEXT NOT NULL,
            output_dir TEXT,
            status TEXT DEFAULT 'running',
            fct_avg REAL,
            fct_99p REAL,
            notes TEXT
        )
        """)

        conn.commit()
        conn.close()

    def parse_log_filename(self, filename):
        """从日志文件名解析实验参数"""
        # autorun_400.sh格式: topo=X_load=X_err=X_cdf=X_cc=X_pfc=X_irn=X_armode=X_timeout=X_win=X_rtoh=X_rtol=X_buf=X_lb=X.log
        # autorun_new.sh格式: topo=X_load=X_err=X_cdf=X_cc=X_pfc=X_irn=X_armode=X_timeout=X_win=X_lb=X.log

        pattern = r'topo=([^_]+)_load=([^_]+)_err=([^_]+)_cdf=([^_]+)_cc=([^_]+)_pfc=([^_]+)_irn=([^_]+)_armode=([^_]+)_timeout=([^_]+)_win=([^_]+)(?:_rtoh=([^_]+)_rtol=([^_]+)_buf=([^_]+))?_lb=([^.]+)\.log'

        match = re.match(pattern, filename)
        if not match:
            return None

        groups = match.groups()

        params = {
            'topology': groups[0],
            'netload': int(groups[1]),
            'error_rate': float(groups[2]),
            'cdf': groups[3],
            'cc': groups[4],
            'pfc': int(groups[5]),
            'irn': int(groups[6]),
            'armode': groups[7],
            'timeout_mode': int(groups[8]),
            'win_size': int(groups[9]),
            'rto_high': int(groups[10]) if groups[10] else None,
            'rto_low': int(groups[11]) if groups[11] else None,
            'buffer_size': int(groups[12]) if groups[12] else None,
            'lb_algorithm': groups[13]
        }

        # 推断带宽
        if '400G' in params['topology']:
            params['bandwidth'] = 400
        elif '200G' in params['topology']:
            params['bandwidth'] = 200
        else:
            params['bandwidth'] = 100

        return params

    def scan_logs(self):
        """扫描logs目录并入库"""
        if not self.logs_dir.exists():
            print(f"日志目录不存在: {self.logs_dir}")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        added = 0
        skipped = 0

        for log_file in self.logs_dir.glob("*.log"):
            # 检查是否已经入库
            cursor.execute("SELECT id FROM experiments WHERE log_file = ?", (str(log_file),))
            if cursor.fetchone():
                skipped += 1
                continue

            params = self.parse_log_filename(log_file.name)
            if not params:
                print(f"无法解析文件名: {log_file.name}")
                continue

            # 获取文件时间戳
            timestamp = datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()

            # 检查实验状态
            status = self.check_experiment_status(log_file)

            cursor.execute("""
            INSERT INTO experiments (
                timestamp, topology, netload, error_rate, cdf, cc, pfc, irn,
                armode, timeout_mode, win_size, rto_high, rto_low, buffer_size,
                bandwidth, lb_algorithm, log_file, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp, params['topology'], params['netload'], params['error_rate'],
                params['cdf'], params['cc'], params['pfc'], params['irn'],
                params['armode'], params['timeout_mode'], params['win_size'],
                params['rto_high'], params['rto_low'], params['buffer_size'],
                params['bandwidth'], params['lb_algorithm'], str(log_file), status
            ))

            added += 1

        conn.commit()
        conn.close()

        print(f"扫描完成: 新增 {added} 条记录, 跳过 {skipped} 条已存在记录")

    def check_experiment_status(self, log_file):
        """检查实验状态"""
        try:
            with open(log_file, 'r') as f:
                content = f.read()
                if "Simulation End" in content or "Analysis Complete" in content:
                    return "completed"
                elif "Error" in content or "FAILED" in content:
                    return "failed"
                else:
                    return "running"
        except:
            return "unknown"

    def query(self, **filters):
        """查询实验记录"""
        conn = sqlite3.connect(self.db_path)

        where_clauses = []
        params = []

        for key, value in filters.items():
            if value is not None:
                if key in ['topology', 'cdf', 'cc', 'armode', 'lb_algorithm', 'status']:
                    where_clauses.append(f"{key} = ?")
                    params.append(value)
                elif key in ['netload', 'pfc', 'irn', 'bandwidth']:
                    where_clauses.append(f"{key} = ?")
                    params.append(int(value))
                elif key == 'error_rate':
                    where_clauses.append(f"{key} = ?")
                    params.append(float(value))

        query = "SELECT * FROM experiments"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY timestamp DESC"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        return df

    def export_summary(self, output_file="experiment_summary.csv"):
        """导出实验汇总"""
        conn = sqlite3.connect(self.db_path)

        summary_query = """
        SELECT
            topology,
            bandwidth,
            cdf,
            cc,
            lb_algorithm,
            COUNT(*) as total_experiments,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
            AVG(CASE WHEN status = 'completed' THEN fct_avg END) as avg_fct
        FROM experiments
        GROUP BY topology, bandwidth, cdf, cc, lb_algorithm
        ORDER BY topology, cc, lb_algorithm
        """

        df = pd.read_sql_query(summary_query, conn)
        conn.close()

        df.to_csv(output_file, index=False)
        print(f"实验汇总已导出到: {output_file}")

        return df

    def cleanup_failed(self):
        """清理失败的实验记录和日志文件"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT log_file FROM experiments WHERE status = 'failed'")
        failed_logs = cursor.fetchall()

        removed = 0
        for (log_file,) in failed_logs:
            log_path = Path(log_file)
            if log_path.exists():
                log_path.unlink()
                removed += 1

        cursor.execute("DELETE FROM experiments WHERE status = 'failed'")
        deleted = cursor.rowcount

        conn.commit()
        conn.close()

        print(f"清理完成: 删除 {removed} 个日志文件, {deleted} 条数据库记录")

    def organize_by_date(self):
        """按日期组织日志文件"""
        if not self.logs_dir.exists():
            return

        for log_file in self.logs_dir.glob("*.log"):
            # 获取文件日期
            file_date = datetime.fromtimestamp(log_file.stat().st_mtime)
            date_dir = self.logs_dir / file_date.strftime("%Y-%m-%d")
            date_dir.mkdir(exist_ok=True)

            # 移动文件
            new_path = date_dir / log_file.name
            if not new_path.exists():
                log_file.rename(new_path)

                # 更新数据库中的路径
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE experiments SET log_file = ? WHERE log_file = ?",
                             (str(new_path), str(log_file)))
                conn.commit()
                conn.close()

def main():
    parser = argparse.ArgumentParser(description="实验历史记录管理工具")
    parser.add_argument('action', choices=['scan', 'query', 'export', 'cleanup', 'organize'],
                       help="执行的操作")
    parser.add_argument('--topology', help="拓扑过滤")
    parser.add_argument('--cc', help="拥塞控制算法过滤")
    parser.add_argument('--lb', help="负载均衡算法过滤")
    parser.add_argument('--status', help="状态过滤")
    parser.add_argument('--bandwidth', type=int, help="带宽过滤")

    args = parser.parse_args()

    manager = ExperimentManager()

    if args.action == 'scan':
        manager.scan_logs()

    elif args.action == 'query':
        filters = {
            'topology': args.topology,
            'cc': args.cc,
            'lb_algorithm': args.lb,
            'status': args.status,
            'bandwidth': args.bandwidth
        }
        # 移除None值
        filters = {k: v for k, v in filters.items() if v is not None}

        results = manager.query(**filters)
        print(f"\n找到 {len(results)} 条记录:")
        print(results[['timestamp', 'topology', 'cc', 'lb_algorithm', 'status', 'log_file']].to_string(index=False))

    elif args.action == 'export':
        summary = manager.export_summary()
        print(summary)

    elif args.action == 'cleanup':
        manager.cleanup_failed()

    elif args.action == 'organize':
        manager.organize_by_date()
        print("日志文件已按日期组织")

if __name__ == "__main__":
    main()