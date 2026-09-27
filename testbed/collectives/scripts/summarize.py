#!/usr/bin/env python3
import argparse
import csv
import math
from pathlib import Path
import statistics
import sys


def main():
    parser = argparse.ArgumentParser(description="Per-file JCT summary; repeats and groups stay separate. p99 uses nearest rank.")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["file", "samples", "mean_us", "median_us", "p99_us", "min_us", "max_us"])
    for path in sorted(args.directory.rglob("*.csv")):
        values = []
        with path.open(newline="") as source:
            reader = csv.DictReader(source)
            if "jct_us" not in (reader.fieldnames or []):
                continue
            for row in reader:
                value = float(row["jct_us"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid JCT in {path}")
                values.append(value)
        if values:
            values.sort()
            writer.writerow([str(path.relative_to(args.directory)), len(values), statistics.mean(values),
                             statistics.median(values), values[math.ceil(0.99 * len(values)) - 1], values[0], values[-1]])


if __name__ == "__main__":
    main()
