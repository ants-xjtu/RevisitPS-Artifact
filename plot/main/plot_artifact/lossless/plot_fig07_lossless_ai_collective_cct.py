#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from plot_common import add_common_args, run_bazel


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Figure 7 lossless AI collective CCT.")
    add_common_args(parser)
    args = parser.parse_args()
    stage_out = args.output_dir / "fig07_lossless_ai_collective_cct"
    run_bazel("//main/plot_sample:plot_sim_ai_jct_avg", [args.input_dir, "-o", stage_out, "--normalize", "--combined", "--all-combos"], dry_run=args.dry_run)
    if args.dry_run:
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(stage_out.glob("*.pdf")):
        shutil.copy2(pdf, args.output_dir / f"fig07_lossless_ai_collective_cct_{pdf.name}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
