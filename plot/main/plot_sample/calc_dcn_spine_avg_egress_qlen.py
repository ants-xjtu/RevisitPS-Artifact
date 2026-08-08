#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import glob
import json
import os


def get_label(series):
    lb = str(series.get("load_balancing_mode", "N/A"))
    rec = str(series.get("recovery_mechanism", "N/A"))
    return f"{lb}({rec})"


def process_file(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)

    series_list = data.get("data_series", [])
    if not series_list:
        print(f"⚠️ No data_series in: {json_path}")
        return

    print(f"--- {json_path} ---")
    for series in series_list:
        label = get_label(series)
        egress_summary = (series.get("egress_data") or {}).get("summary", {})
        avg_bytes = float(egress_summary.get("avg_qlen_bytes", 0) or 0)
        avg_kb = avg_bytes / 1024.0
        print(f"{label:24s} avg_egress_qlen = {avg_bytes:.2f} B ({avg_kb:.2f} KB)")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate average egress queue length from spine QLen JSON data."
    )
    parser.add_argument(
        "input_path",
        help="A single JSON file or a directory containing JSON files.",
    )
    args = parser.parse_args()

    input_path = os.path.abspath(os.path.expanduser(args.input_path))
    if os.path.isfile(input_path):
        process_file(input_path)
        return

    if os.path.isdir(input_path):
        json_files = sorted(glob.glob(os.path.join(input_path, "*.json")))
        if not json_files:
            print(f"⚠️ No .json files found in: {input_path}")
            return
        for path in json_files:
            process_file(path)
        return

    print(f"❌ Invalid path: {input_path}")


if __name__ == "__main__":
    main()
