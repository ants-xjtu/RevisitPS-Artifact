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
    Parses a single FCT CSV file, calculates raw FCT statistics (avg, p99),
    and returns the FCTs from the largest flow-size bucket.
    """
    flows = []
    with open(filename, "r") as f:
        reader = csv.reader(f)
        header = next(reader, None)
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

    flows = sorted(flows, key=lambda x: x[1])
    nn = len(flows)
    bucket_data = []

    # --- MODIFICATION START ---
    # Variable to store the FCTs of the largest bucket
    largest_bucket_fcts = []
    # --- MODIFICATION END ---

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

        # --- MODIFICATION START ---
        # If this is the last bucket, capture its FCTs.
        # Since flows are sorted by size, this is the bucket with the largest flows.
        if i == num_buckets - 1:
            largest_bucket_fcts = fcts_in_chunk
        # --- MODIFICATION END ---

        avg_fct = sum(fcts_in_chunk) / len(fcts_in_chunk)
        p99_fct = get_pctl(sorted(fcts_in_chunk), 0.99)
        size_for_bucket = max(sizes_in_chunk)

        print(f"Bucket {i+1}/{num_buckets}: size={size_for_bucket}, avgFCT={avg_fct:.3f}, p99FCT={p99_fct:.3f}")

        bucket_data.append({
            "size": size_for_bucket,
            "avg": avg_fct,
            "p99": p99_fct,
        })

    bucket_data = sorted(bucket_data, key=lambda x: x['size'])

    result = {
        "avg": [item['avg'] for item in bucket_data],
        "p99": [item['p99'] for item in bucket_data],
        "size": [item['size'] for item in bucket_data],
        # --- MODIFICATION START ---
        # Add the captured FCTs to the return dictionary
        "largest_bucket_fcts": largest_bucket_fcts
        # --- MODIFICATION END ---
    }
    return result

def write_fcts_to_csv(filename, fcts):
    """Writes a list of FCTs to a new CSV file."""
    if not fcts:
        print(f"⚠️ No FCTs to write for {filename}.")
        return

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['fct'])  # Write header
        for fct in fcts:
            writer.writerow([fct])
    print(f"✅ FCTs from the largest bucket saved to: {filename}")


def format_load_balancing_label(label):
    """Formats raw CSV-derived labels for plot legends."""
    normalized = label.lower()
    if "rps" in normalized:
        return "RPS"
    if "ecmp" in normalized:
        return "ECMP"
    if "bigsw" in normalized or "bigswitch" in normalized:
        return "BigSwitch"
    return label


def main():
    parser = argparse.ArgumentParser(
        description="Parse multiple FCT CSV files, normalize against bigswitch, and combine into JSON."
    )
    parser.add_argument(
        "csv_files",
        nargs='+',
        help="One or more input CSV files (e.g., ecmp_50.csv rps_50.csv bigswitch_50.csv)."
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="combined_fct_plot_data.json",
        help="Output JSON file name."
    )
    args = parser.parse_args()

    raw_data = {}

    print("--- Starting to process files ---")
    for csv_file in args.csv_files:
        if not os.path.exists(csv_file):
            print(f"❌ Error: File not found: {csv_file}")
            continue

        print(f"\nProcessing {csv_file}...")
        parsed_result = parse_fct_csv(csv_file)
        if not parsed_result:
            continue

        base_name = os.path.basename(csv_file)
        label = os.path.splitext(base_name)[0]
        raw_data[label] = parsed_result

        # --- MODIFICATION START ---
        # Get the FCTs from the result and write them to a new file
        fcts_to_write = parsed_result.get("largest_bucket_fcts")
        if fcts_to_write:
            # Create a descriptive output filename
            output_fct_filename = f"largest_bucket_fcts_{base_name}"
            write_fcts_to_csv(output_fct_filename, fcts_to_write)
        # --- MODIFICATION END ---

    # The rest of the original logic for creating the JSON file remains unchanged
    # 找到 bigswitch baseline
    baseline_key = None
    for key in raw_data:
        if "bigsw" in key.lower():
            baseline_key = key
            break

    if not baseline_key:
        print("\n❌ Error: No bigswitch file found in input. Cannot normalize for JSON output.")
        # We can still proceed without normalization if desired, or just stop.
        # For now, we will stop the JSON creation part.
        return

    baseline = raw_data[baseline_key]

    output_data = {
        "metadata": {
            "topology": "N/A",
            "network_load": "N/A",
            "load_type": "N/A"
        },
        "data_series": []
    }

    for label, result in raw_data.items():
        # Ensure the lists are of the same length before zipping
        if len(result["avg"]) != len(baseline["avg"]) or len(result["p99"]) != len(baseline["p99"]):
            print(f"⚠️ Warning: Mismatch in bucket count for {label} compared to baseline. Skipping normalization.")
            continue

        norm_avg = [a / b for a, b in zip(result["avg"], baseline["avg"])]
        norm_p99 = [a / b for a, b in zip(result["p99"], baseline["p99"])]

        series_entry = {
            "load_balancing_mode": format_load_balancing_label(label),
            "recovery_mechanism": "N/A",
            "flow_size_buckets_bytes": result["size"],
            "avg_fct_normalized": norm_avg,
            "p99_fct_normalized": norm_p99
        }
        output_data["data_series"].append(series_entry)

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=4)

    print(f"\n✅ All files processed. Normalized JSON data saved to: {args.output}")

if __name__ == "__main__":
    main()
