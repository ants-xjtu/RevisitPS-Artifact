#!/usr/bin/env python3
from __future__ import annotations

import argparse
from plot_common import add_common_args, copy_file, run_bazel, temporary_workdir


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 9 lossless queue per PFC event.")
    add_common_args(parser)
    args = parser.parse_args()
    input_json = args.input_dir / "fig09_lossless_queue_per_pfc_event.json"
    with temporary_workdir("fig09", dry_run=args.dry_run) as workdir:
        prefix = workdir / "fig09_lossless_queue_per_pfc_event"
        run_bazel(
            "//main/plot_sample:plot_dcn_pfc_incast",
            [input_json, "--output-prefix", prefix, "--queue-x-max", 4],
            dry_run=args.dry_run,
        )
        copy_file(workdir / "fig09_lossless_queue_per_pfc_event_queue_bytes.pdf", args.output_dir / "fig09_lossless_queue_per_pfc_event.pdf", dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
