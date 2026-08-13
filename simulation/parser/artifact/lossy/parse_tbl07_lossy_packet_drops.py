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


OUTPUT = "tbl07_lossy_packet_drops"
SCHEMES = [
    "ECMP (NAK+SR)",
    "AR (RTO+GBN)",
    "AR (Packet trimming)",
    "AR (RTO+GBN+Slow Start)",
    "AR (Packet trimming+Slow Start)",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Table 7 packet drops.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("tbl07-history", dry_run=args.dry_run) as work:
        selected = work / "table7.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            topologies={"fat_k8_100G_OS1"},
            workloads={"AliStorage2019"},
            algorithms={"ECMP", "AR"},
            recipes={"f12_baseline", "f12_ar_rto", "f12_ar_trim"},
            expected=5,
            dry_run=args.dry_run,
        )
        build_lossy_drop_table(
            table_number=7,
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
