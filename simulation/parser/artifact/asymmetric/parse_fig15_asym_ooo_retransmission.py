#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    copy_matching,
    copy_one,
    resolve_run_paths,
    select_asymmetric_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "fig15_asym_ooo_retransmission"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 15 OOO/retransmission.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig15-history", dry_run=args.dry_run) as work:
        selected = work / "fig15_asym_ooo_retransmission.history"
        select_asymmetric_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure15"},
            expected=16,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_ooo.py",
            [selected],
            dry_run=args.dry_run,
        ) as stage:
            copy_matching(
                stage / "parser" / "json-data-ooo-asy",
                "OOO_DATA_*.json",
                paths.output_dir,
                dry_run=args.dry_run,
            )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_unnecc_retrans.py",
            [selected],
            dry_run=args.dry_run,
        ):
            for suffix in ("retrans_trace.csv", "retrans_summary.txt"):
                copy_one(
                    work / f"fig15_asym_ooo_retransmission_{suffix}",
                    paths.output_dir / f"fig15_asym_ooo_retransmission_{suffix}",
                    dry_run=args.dry_run,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
