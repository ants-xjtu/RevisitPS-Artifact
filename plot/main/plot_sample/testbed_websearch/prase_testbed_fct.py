#!/usr/bin/python3
import argparse
import json
import csv
import os
from collections import defaultdict


def get_pctl(a, p):
    """Calculates the p-th percentile of a sorted list."""
    i = int(len(a) * p)
    if i >= len(a):
        i = len(a) - 1
    if i < 0:
        return 0
    return a[i]


def reorder_within_same_size(flows, internal_reorder_buckets=100):
    """
    Input: flows = list of [slowdown, size]
    Output: reordered flows where, for each fixed size, slowdowns are evenly interleaved
            using round-robin across internal buckets (like your raw version).
    NOTE: The final order across different sizes is still increasing by size.
    """
    flows_by_size = defaultdict(list)
    for slowdown, size in flows:
        flows_by_size[size].append(slowdown)

    reordered = []
    for size in sorted(flows_by_size.keys()):
        slowdowns = sorted(flows_by_size[size])
        n = len(slowdowns)
        if n == 0:
            continue

        B = min(internal_reorder_buckets, n)
        buckets = [[] for _ in range(B)]
        for i, s in enumerate(slowdowns):
            buckets[i % B].append(s)

        # flatten buckets in order
        for b in buckets:
            for s in b:
                reordered.append([s, size])

    return reordered


def parse_fct_csv(
    filename,
    num_buckets=19,
    max_slowdown=400.0,
    verbose_drop=False,
    internal_reorder_buckets=100,
    enable_filter=True,
):
    """
    Parses a single FCT CSV file and calculates slowdown statistics,
    bucketing the results by FLOW SIZE for an ordered x-axis.

    Improvement:
    - Evenly interleave flows of the SAME size (raw-style round-robin buckets)
      before doing the final size-based bucketing.

    Filters out flows with slowdown > max_slowdown if enable_filter=True.
    """
    flows = []
    dropped = 0
    total = 0

    with open(filename, "r") as f:
        reader = csv.reader(f)
        _header = next(reader, None)  # Skip header
        for row in reader:
            if len(row) < 2:
                continue

            try:
                size = int(float(row[0]))
                fct = float(row[1])
            except ValueError:
                continue

            ideal_fct = 8 + size * 8 / 1000000  # Ideal FCT in ms (your version)
            if ideal_fct <= 0:
                continue

            slowdown = fct / ideal_fct
            if slowdown < 1:
                slowdown = 1

            total += 1
            # if enable_filter and slowdown > max_slowdown:
            #     dropped += 1
            #     if verbose_drop:
            #         print(
            #             f"DROP: size={size}, fct={fct:.6f}, ideal={ideal_fct:.6f}, slowdown={slowdown:.3f}"
            #         )
            #     continue

            flows.append([slowdown, size])

    if not flows:
        print(f"⚠️ No valid data read from {filename} after filtering. Check the CSV format / thresholds.")
        return None

    if enable_filter and dropped > 0:
        ratio = (dropped / max(total, 1)) * 100.0
        print(
            f"Filtered out {dropped}/{total} flows ({ratio:.2f}%) with slowdown > {max_slowdown} in {filename}"
        )

    # --- Optimization: evenly interleave within SAME size (raw-style) ---
    flows = reorder_within_same_size(flows, internal_reorder_buckets=internal_reorder_buckets)

    # --- Grouping by FLOW SIZE (ordered x-axis) ---
    # After reorder, it is already size-sorted, but keep it explicit in case of changes.
    flows = sorted(flows, key=lambda x: x[1])
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

        slowdowns_in_chunk = [x[0] for x in chunk]
        sizes_in_chunk = [x[1] for x in chunk]

        avg_slowdown = sum(slowdowns_in_chunk) / len(slowdowns_in_chunk)
        p99_slowdown = get_pctl(sorted(slowdowns_in_chunk), 0.99)

        # bucket size label: max / median / etc.
        size_for_bucket = max(sizes_in_chunk)

        print(
            f"Bucket {i+1}/{num_buckets}: size={size_for_bucket}, avg={avg_slowdown:.3f}, p99={p99_slowdown:.3f}"
        )

        bucket_data.append({"size": size_for_bucket, "avg": avg_slowdown, "p99": p99_slowdown})

    bucket_data = sorted(bucket_data, key=lambda x: x["size"])

    return {
        "avg": [item["avg"] for item in bucket_data],
        "p99": [item["p99"] for item in bucket_data],
        "size": [item["size"] for item in bucket_data],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse multiple FCT CSV files and combine them into a single JSON for plotting."
    )
    parser.add_argument(
        "csv_files",
        nargs="+",
        help="One or more input CSV files (e.g., ecmp_50.csv rps_50.csv).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="combined_fct_plot_data.json",
        help="Output JSON file name.",
    )
    parser.add_argument(
        "--num-buckets",
        type=int,
        default=19,
        help="Number of flow-size buckets for the x-axis.",
    )
    parser.add_argument(
        "--max-slowdown",
        type=float,
        default=400.0,
        help="Filter out flows with slowdown greater than this value.",
    )
    parser.add_argument(
        "--verbose-drop",
        action="store_true",
        help="Print each dropped flow (can be very noisy).",
    )
    parser.add_argument(
        "--internal-reorder-buckets",
        type=int,
        default=100,
        help="How many sub-buckets to use when interleaving flows within the same size.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable max-slowdown filtering (keep all flows).",
    )

    args = parser.parse_args()

    output_data = {
        "metadata": {
            "topology": "N/A",
            "network_load": "N/A",
            "load_type": "N/A",
            "num_buckets": args.num_buckets,
            "max_slowdown": args.max_slowdown,
            "internal_reorder_buckets": args.internal_reorder_buckets,
            "filter_enabled": (not args.no_filter),
        },
        "data_series": [],
    }

    print("--- Starting to process files ---")
    for csv_file in args.csv_files:
        if not os.path.exists(csv_file):
            print(f"❌ Error: File not found: {csv_file}")
            continue

        print(f"Processing {csv_file}...")
        parsed_result = parse_fct_csv(
            csv_file,
            num_buckets=args.num_buckets,
            max_slowdown=args.max_slowdown,
            verbose_drop=args.verbose_drop,
            internal_reorder_buckets=args.internal_reorder_buckets,
            enable_filter=(not args.no_filter),
        )

        if not parsed_result:
            continue

        base_name = os.path.basename(csv_file)
        label = os.path.splitext(base_name)[0]

        series_entry = {
            "load_balancing_mode": label,
            "recovery_mechanism": "N/A",
            "flow_size_buckets_bytes": parsed_result["size"],
            "avg_fct_slowdown": parsed_result["avg"],
            "p99_fct_slowdown": parsed_result["p99"],
        }
        output_data["data_series"].append(series_entry)

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=4)

    print(f"\n✅ All files processed. Combined data saved to: {args.output}")


if __name__ == "__main__":
    main()
