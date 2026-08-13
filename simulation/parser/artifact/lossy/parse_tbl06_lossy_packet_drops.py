#!/usr/bin/env python3
from __future__ import annotations

import argparse

from artifact_common import (
    add_common_args,
    resolve_run_paths,
    select_manifest_history,
    temporary_workdir,
)
from lossy_drop_table import build_lossy_drop_table


OUTPUT = "tbl06_lossy_packet_drops"
SCHEMES = ["ECMP (NAK+SR)", "ConWeave (NAK+SR)", "AR (RTO+GBN)"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 6 packet drops.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("tbl06-history", dry_run=args.dry_run) as work:
        selected = work / "table6.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            topologies={"leaf_spine_L8_S16_100G_OS1"},
            workloads={"AliStorage2019"},
            recipes={"f11_baseline", "f11_ar_rto"},
            expected=3,
            dry_run=args.dry_run,
        )
        build_lossy_drop_table(
            table_number=6,
            manifest=paths.manifest,
            selected_history=selected,
            ns3_root=args.ns3_root,
            output_dir=paths.output_dir,
            table_dir=paths.table_dir,
            scheme_order=SCHEMES,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
