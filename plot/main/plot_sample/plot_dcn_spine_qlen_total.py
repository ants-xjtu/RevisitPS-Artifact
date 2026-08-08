#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import json
import matplotlib.pyplot as plt
import os
import glob

# Import the project's plotting library
import lib.py.plot.plot as plot

def draw_qlen_plots(json_path, output_prefix):
    """
    新的绘图逻辑（根据用户要求）：
    - 分别画 Ingress 与 Egress 两张图
    - 每张图的 x 轴为 ['Average', 'p99']
    - 每个 load_balancing_mode + recovery_mechanism 作为一条 series（颜色/图例）
    """
    with open(json_path, 'r') as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    data_series_list = data.get("data_series", [])
    
    if not data_series_list:
        print(f"No valid 'data_series' found in file {json_path}. Skipping.")
        return

    # --- 数据收集（按配置收集 ingress/egress 的 avg 与 p99） ---
    config_labels = []
    ingress_metrics = []  # 每项为 [avg_ingress, p99_ingress]
    egress_metrics = []   # 每项为 [avg_egress, p99_egress]

    for series in data_series_list:
        label = f"{series.get('load_balancing_mode', 'N/A')}\n({series.get('recovery_mechanism', 'N/A')})"
        config_labels.append(label)

        ingress_summary = (series.get("ingress_data") or {}).get("summary", {})
        avg_ing = ingress_summary.get("avg_qlen_bytes", 0) or 0
        p99_ing = ingress_summary.get("p99_qlen_bytes", 0) or 0
        ingress_metrics.append([avg_ing, p99_ing])

        egress_summary = (series.get("egress_data") or {}).get("summary", {})
        avg_eg = egress_summary.get("avg_qlen_bytes", 0) or 0
        p99_eg = egress_summary.get("p99_qlen_bytes", 0) or 0
        egress_metrics.append([avg_eg, p99_eg])

    title_info = (f"Topology: {metadata.get('topology', 'N/A')}, "
                  f"Load: {metadata.get('network_load', 'N/A')}")

    # --- Ingress: x = ['Average', 'p99'], 每个 config 为一条 series ---
    xlabels = ['Average', 'p99']
    p_ing = plot.BarPlot()
    for vals, lbl in zip(ingress_metrics, config_labels):
        # vals 长度应为 len(xlabels)
        p_ing.insert_yvals(vals, label=lbl)

    p_ing.ax.set_ylabel("Queue Length (Bytes)")
    p_ing.ax.set_yscale('log')
    p_ing.ax.set_title(f"Ingress Queue Length\n({title_info})", fontsize=14)
    p_ing.plot(xlabels=xlabels)

    p_ing.ax.tick_params(axis='y', labelsize=12)
    plt.setp(p_ing.ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor", fontsize=10)
    p_ing.ax.legend(fontsize=10, bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout(pad=1.5)

    ingress_output_path = f"{output_prefix}_ingress_grouped.pdf"
    plt.savefig(ingress_output_path)
    plt.close()
    print(f"✅ Ingress grouped chart saved to: {ingress_output_path}")

    # --- Egress: x = ['Average', 'p99'], 每个 config 为一条 series ---
    p_eg = plot.BarPlot()
    for vals, lbl in zip(egress_metrics, config_labels):
        p_eg.insert_yvals(vals, label=lbl)

    p_eg.ax.set_ylabel("Queue Length (Bytes)")
    p_eg.ax.set_yscale('log')
    p_eg.ax.set_title(f"Egress Queue Length\n({title_info})", fontsize=14)
    p_eg.plot(xlabels=xlabels)

    p_eg.ax.tick_params(axis='y', labelsize=12)
    plt.setp(p_eg.ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor", fontsize=10)
    p_eg.ax.legend(fontsize=10, bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout(pad=1.5)

    egress_output_path = f"{output_prefix}_egress_grouped.pdf"
    plt.savefig(egress_output_path)
    plt.close()
    print(f"✅ Egress grouped chart saved to: {egress_output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Draw queue length (QLen) bar charts from JSON files."
    )
    parser.add_argument(
        "input_path",
        type=str,
        help="Input path, which can be a single JSON file or a directory containing multiple JSON files."
    )
    args = parser.parse_args()

    input_path = args.input_path

    if os.path.isfile(input_path):
        json_file = input_path
        dir_name = os.path.dirname(json_file)
        base_name = os.path.basename(json_file)
        output_prefix = os.path.join(dir_name, os.path.splitext(base_name)[0])
        print(f"--- Processing {json_file} ---")
        draw_qlen_plots(json_file, output_prefix)

    elif os.path.isdir(input_path):
        json_files = sorted(glob.glob(os.path.join(input_path, '*.json')))
        if not json_files:
            print(f"⚠️ No .json files found in the directory {input_path}.")
            return
        
        print(f"Found {len(json_files)} JSON files, starting processing...")
        for json_file in json_files:
            base_name = os.path.basename(json_file)
            output_prefix = os.path.join(input_path, os.path.splitext(base_name)[0])
            print(f"--- Processing {json_file} ---")
            draw_qlen_plots(json_file, output_prefix)
        print("\n✅ All files processed!")

    else:
        print(f"Error: {input_path} is not a valid file or directory.")
        return


if __name__ == '__main__':
    main()
