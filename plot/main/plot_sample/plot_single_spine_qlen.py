#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 你的项目自带绘图库
import lib.py.plot.plot as plot


def plot_spine_egress_from_json(json_file, spine_id, top_n=4, y_step=200,
                                smooth=5):
    """
    从 JSON 文件中读取数据，并为指定 Spine 绘制所有端口的出口队列长度随时间变化。
    图像将保存到 JSON 文件所在目录。
    """
    # 1. 读取 JSON 文件
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 找不到文件: {json_file}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        return

    # 2. 提取所有端口数据
    egress_ports = {}
    for series in data.get("data_series", []):
        for port_key, port_data in series.get("egress_data_by_port", {}).items():
            try:
                parts = port_key.split("_")
                node_id = int(parts[1])
                port_id = int(parts[3])
            except Exception:
                continue
            if node_id == spine_id:
                egress_ports[port_id] = port_data["time_series"]

    if not egress_ports:
        print(f"⚠️ 在 JSON 中没有找到 Spine {spine_id} 的端口数据")
        return

    # 3. 选 max(qlen_kb) 最大的 TopN 个端口（默认 4）
    port_candidates = []
    for port_id, ts_data in sorted(egress_ports.items()):
        if port_id == 9:
            continue  # 跳过 port 9
        qlen_kb = pd.Series(ts_data["qlen_bytes"]) / 1024.0
        timestamps_ms = [(t - 2_000_000_000) / 1_000_000 for t in ts_data["timestamps_ns"]]
        port_candidates.append((port_id, qlen_kb, timestamps_ms, float(qlen_kb.max())))

    top_ports = sorted(port_candidates, key=lambda x: x[3], reverse=True)[:top_n]
    # 按 port_id 排序画，图例更整齐
    top_ports.sort(key=lambda x: x[0])

    # 4. 绘图
    p = plot.LineDashPlot(nplots=1)
    p.fig.set_size_inches(8, 4)
    # 保留项目默认颜色，配合线型和稀疏 marker 增强区分度。
    p.set_dashstyles((
        {"dashes": (1, 0),                     "linewidth": 2.8},   # 实线
        {"dashes": (9, 3),                     "linewidth": 2.5},   # 长虚
        {"dashes": (1, 2.2),                   "linewidth": 3.2},   # 点线（加粗才显）
        {"dashes": (6, 2, 1, 2),               "linewidth": 2.5},   # dash-dot
        {"dashes": (4, 2, 1, 2, 1, 2),         "linewidth": 2.5},   # dash-dot-dot
        {"dashes": (12, 3, 3, 3),              "linewidth": 2.5},   # long dash-dot
        {"dashes": (2, 2),                     "linewidth": 2.7},   # short dash
        {"dashes": (7, 2, 2, 2, 2, 2),         "linewidth": 2.5},   # mixed
    ))
    ax = p.axes[0]
    has_data = False
    markers = ("o", "s", "^", "D", "v", "P", "X", "*")

    for idx, (port_id, qlen_kb, timestamps_ms, _peak) in enumerate(top_ports):
        if smooth and smooth > 1:
            qlen_kb = qlen_kb.rolling(window=smooth, center=True,
                                       min_periods=1).mean()
        markevery = max(1, len(timestamps_ms) // 18)
        p.plot(
            timestamps_ms,
            qlen_kb,
            axid=0,
            label=f"Port {port_id}",
            marker=markers[idx % len(markers)],
            markevery=markevery,
            markersize=7.0,
            markerfacecolor="white",
            markeredgewidth=1.2,
            alpha=0.95,
        )
        has_data = True

    if has_data:
        ax.set_ylabel("Queue Length (KB)", fontsize=20)
        ax.set_xlabel("Time (ms)", fontsize=20)
        ax.tick_params(axis='both', labelsize=15)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_locator(plt.MultipleLocator(y_step))

        leg = ax.legend(
            fontsize=15,
            loc='upper left',
            ncol=1,
            frameon=False
        )
        leg.set_zorder(100)

        p.fig.tight_layout(pad=1.5)

        # 4. 保存到 JSON 文件所在目录
        output_dir = os.path.dirname(os.path.abspath(json_file))
        output_file = os.path.join(output_dir, f"spine_{spine_id}_egress_qlen.pdf")
        plt.savefig(output_file)
        plt.close(p.fig)
        print(f"✅ 图像已保存到: {output_file}")
    else:
        print("⚠️ 没有数据，未生成图。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="绘制指定 Spine 的所有端口出口队列长度")
    parser.add_argument("json_file", type=str, help="输入 JSON 文件路径")
    parser.add_argument("--spine_id", type=int, required=True, help="要绘制的 Spine ID")
    parser.add_argument("--top_n", type=int, default=4,
                        help="只画峰值 qlen 最大的 N 个端口 (默认 4)")
    parser.add_argument("--y_step", type=float, default=200,
                        help="Y 轴刻度步长 (KB, 默认 200)")
    parser.add_argument("--smooth", type=int, default=5,
                        help="滚动平均窗口大小 (默认 5；<=1 表示不平滑)")
    args = parser.parse_args()

    plot_spine_egress_from_json(args.json_file, args.spine_id,
                                top_n=args.top_n, y_step=args.y_step,
                                smooth=args.smooth)
