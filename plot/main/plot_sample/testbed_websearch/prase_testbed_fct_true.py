#!/usr/bin/python3
import argparse
import json
import csv
import os

def get_pctl(a, p):
    """Calculates the p-th percentile of a sorted list."""
    i = int(len(a) * p)
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0
    return a[i]

def parse_fct_csv(filename, num_buckets=19):
    """
    Parses a single FCT CSV file and calculates raw FCT statistics (avg, p99),
    bucketing the results by FLOW SIZE for an ordered x-axis.
    """
    flows = []
    with open(filename, "r") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 2:
                continue
            try:
                size = int(float(row[0]))
                fct = float(row[1])
            except ValueError:
                continue

            if fct <= 0:
                continue

            flows.append([fct, size])

    if not flows:
        print(f"⚠️ No valid data read from {filename}. Check the CSV format.")
        return None

    # --- Grouping by FLOW SIZE ---
    flows = sorted(flows, key=lambda x: x[1])  # 按 size 排序
    nn = len(flows)
    bucket_data = []

    for i in range(num_buckets):
        l = int(i * nn / num_buckets)
        r = int((i + 1) * nn / num_buckets)
        if i == num_buckets - 1:
            r = nn

        chunk = flows[l:r]
        if not chunk:
            continue

        fcts_in_chunk = [x[0] for x in chunk]
        sizes_in_chunk = [x[1] for x in chunk]

        avg_fct = sum(fcts_in_chunk) / len(fcts_in_chunk)
        p99_fct = get_pctl(sorted(fcts_in_chunk), 0.99)
        size_for_bucket = max(sizes_in_chunk)

        print(f"Bucket {i+1}/{num_buckets}: size={size_for_bucket}, avgFCT={avg_fct:.3f}, p99FCT={p99_fct:.3f}")

        bucket_data.append({
            "size": size_for_bucket,
            "avg": avg_fct,
            "p99": p99_fct,
        })

    # 按 size 排序输出（可选）
    bucket_data = sorted(bucket_data, key=lambda x: x['size'])

    result = {
        "avg": [item['avg'] for item in bucket_data],
        "p99": [item['p99'] for item in bucket_data],
        "size": [item['size'] for item in bucket_data]
    }
    return result

def main():
    parser = argparse.ArgumentParser(
        description="Parse multiple FCT CSV files and combine them into a single JSON for plotting."
    )
    parser.add_argument(
        "csv_files",
        nargs='+',
        help="One or more input CSV files (e.g., ecmp_50.csv rps_50.csv)."
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="combined_fct_plot_data.json",
        help="Output JSON file name."
    )
    args = parser.parse_args()

    output_data = {
        "metadata": {
            "topology": "N/A",
            "network_load": "N/A",
            "load_type": "N/A"
        },
        "data_series": []
    }

    print("--- Starting to process files ---")
    for csv_file in args.csv_files:
        if not os.path.exists(csv_file):
            print(f"❌ Error: File not found: {csv_file}")
            continue

        print(f"Processing {csv_file}...")
        parsed_result = parse_fct_csv(csv_file)

        if not parsed_result:
            continue

        base_name = os.path.basename(csv_file)
        label = os.path.splitext(base_name)[0]

        series_entry = {
            "load_balancing_mode": label,
            "recovery_mechanism": "N/A",
            "flow_size_buckets_bytes": parsed_result["size"],
            "avg_fct": parsed_result["avg"],
            "p99_fct": parsed_result["p99"]
        }
        output_data["data_series"].append(series_entry)

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=4)

    print(f"\n✅ All files processed. Combined data saved to: {args.output}")

if __name__ == "__main__":
    main()
