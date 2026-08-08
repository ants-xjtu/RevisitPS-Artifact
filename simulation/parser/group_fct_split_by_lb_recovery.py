#!/usr/bin/python3

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT_DIR = Path(__file__).with_name("json-data-fct-split")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("json-data-fct-lb-recovery-grouped")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Group split FCT JSON files by load_balancing_mode and recovery_mechanism."
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing split JSON files. Default: %(default)s",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for grouped JSON files. Default: %(default)s",
    )
    return parser.parse_args()


def sanitize_filename(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def sort_buffer_size(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def build_grouped_payloads(input_dir):
    grouped = defaultdict(list)

    for path in sorted(input_dir.glob("*.json")):
        with path.open() as fh:
            payload = json.load(fh)

        x_axis = payload.get("x_axis_percentiles", [])
        metadata = payload.get("metadata", {})
        series_by_group = defaultdict(list)

        for series in payload.get("data_series", []):
            lb_mode = series.get("load_balancing_mode")
            recovery = series.get("recovery_mechanism")
            if not lb_mode or not recovery:
                continue
            series_by_group[(lb_mode, recovery)].append(series)

        for (lb_mode, recovery), matched_series in series_by_group.items():
            buffer_size = (
                metadata.get("buffer_size")
                or matched_series[0].get("buffer_size")
                or "unknown"
            )
            grouped[(lb_mode, recovery)].append(
                {
                    "buffer_size": str(buffer_size),
                    "source_file": path.name,
                    "metadata": metadata,
                    "x_axis_percentiles": x_axis,
                    "data_series": matched_series,
                }
            )

    return grouped


def write_grouped_files(grouped, output_dir, input_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    for (lb_mode, recovery), variants in sorted(grouped.items()):
        variants.sort(key=lambda item: sort_buffer_size(item["buffer_size"]))
        unique_buffer_sizes = []
        seen = set()
        for variant in variants:
            buffer_size = variant["buffer_size"]
            if buffer_size in seen:
                continue
            seen.add(buffer_size)
            unique_buffer_sizes.append(buffer_size)
        output_path = output_dir / f"{sanitize_filename(lb_mode)}__{sanitize_filename(recovery)}.json"
        payload = {
            "group": {
                "load_balancing_mode": lb_mode,
                "recovery_mechanism": recovery,
            },
            "source_dir": str(input_dir),
            "buffer_sizes": unique_buffer_sizes,
            "variants": variants,
        }
        with output_path.open("w") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    grouped = build_grouped_payloads(input_dir)
    write_grouped_files(grouped, output_dir, input_dir)
    print(f"wrote {len(grouped)} grouped files to {output_dir}")


if __name__ == "__main__":
    main()
