#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, resolve_run_paths, run, select_manifest_history, temporary_workdir

OUTPUT = "fig12_lossy_dcn_p99_fct_fattree"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 12 lossy P99 FCT.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig12-history", dry_run=args.dry_run) as work:
        selected = work / "figure12.history"
        select_manifest_history(paths.manifest, paths.history, selected, figures={"figure12"}, expected=7, dry_run=args.dry_run)
        if not args.dry_run:
            paths.output_dir.mkdir(parents=True, exist_ok=True)
        run(["python3", args.ns3_root / "parser" / "parse_dcn_fct_rto.py", selected, "-o", paths.output_dir], dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
