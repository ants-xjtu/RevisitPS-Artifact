#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, resolve_run_paths, run, select_asymmetric_manifest_history, temporary_workdir


OUTPUT = "fig16_asym_packet_trim_rto"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 16 trimming vs RTO.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig16-history", dry_run=args.dry_run) as work:
        selected = work / "figure16.history"
        select_asymmetric_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure16"},
            workloads={"FbHdp2015"},
            expected=6,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            paths.output_dir.mkdir(parents=True, exist_ok=True)
        run(["python3", args.ns3_root / "parser" / "parse_dcn_fct_rto.py", selected, "-o", paths.output_dir], dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
