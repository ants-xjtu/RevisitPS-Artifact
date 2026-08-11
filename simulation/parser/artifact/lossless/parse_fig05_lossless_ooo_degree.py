#!/usr/bin/env python3
from __future__ import annotations

import argparse
from artifact_common import (
    add_common_args,
    copy_one,
    resolve_run_paths,
    select_manifest_history,
    temporary_parser_stage,
    temporary_workdir,
)


OUTPUT = "fig05_lossless_ooo_degree"
SOURCE = "OOO_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Figure 5 lossless OOO degree.")
    add_common_args(parser)
    args = parser.parse_args()
    paths = resolve_run_paths(args, OUTPUT)
    with temporary_workdir("fig05-history", dry_run=args.dry_run) as work:
        selected = work / "figure5.history"
        select_manifest_history(
            paths.manifest,
            paths.history,
            selected,
            figures={"figure5"},
            expected=5,
            dry_run=args.dry_run,
        )
        with temporary_parser_stage(
            args.ns3_root,
            "parse_dcn_ooo.py",
            [selected],
            dry_run=args.dry_run,
        ) as stage:
            copy_one(
                stage / "parser" / "json-data-ooo-asy" / SOURCE,
                paths.output_dir / f"{OUTPUT}.json",
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
