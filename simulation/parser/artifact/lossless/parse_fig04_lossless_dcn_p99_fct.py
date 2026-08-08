#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import add_common_args, run, select_history_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 4 lossless DCN P99 FCT JSON.")
    add_common_args(parser)
    args = parser.parse_args()
    select_history_rows(
        args.history,
        args.selected_history,
        lambda f: (f[15] == "leaf_spine_128_100G_OS2" and f[17] == "AliStorage2019" and f[18] == "80")
        or (f[15] == "fat_k8_100G_OS1" and f[17] == "AliStorage2019" and f[18] == "80"),
        expected=10,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    backend = args.ns3_root / "parser" / "parse_dcn_fct_rto.py"
    run(["python3", backend, args.selected_history, "-o", args.output_dir], dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
