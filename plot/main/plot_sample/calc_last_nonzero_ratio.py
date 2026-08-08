#!/usr/bin/python3

import argparse
import os


def parse_last_value(line):
    parts = line.strip().split()
    if not parts:
        return None
    try:
        return float(parts[-1])
    except ValueError:
        return None


def calc_ratio(path):
    total_lines = 0
    nonzero_lines = 0

    with open(path, "r") as f:
        for line in f:
            value = parse_last_value(line)
            if value is None:
                continue
            total_lines += 1
            if value != 0:
                nonzero_lines += 1

    ratio = (nonzero_lines / total_lines) if total_lines > 0 else 0.0
    return total_lines, nonzero_lines, ratio


def main():
    parser = argparse.ArgumentParser(
        description="Count the ratio of lines whose last numeric field is non-zero."
    )
    parser.add_argument("input_file", help="Input text file path.")
    args = parser.parse_args()

    input_file = os.path.abspath(os.path.expanduser(args.input_file))
    if not os.path.isfile(input_file):
        print(f"Error: invalid file: {input_file}")
        return

    total_lines, nonzero_lines, ratio = calc_ratio(input_file)
    print(f"file: {input_file}")
    print(f"total_valid_lines: {total_lines}")
    print(f"last_value_nonzero_lines: {nonzero_lines}")
    print(f"ratio: {ratio:.6f}")
    print(f"percentage: {ratio * 100:.4f}%")


if __name__ == "__main__":
    main()
