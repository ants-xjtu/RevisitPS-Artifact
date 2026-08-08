#!/usr/bin/env python3
"""Shared helpers for lossless artifact parser wrappers.

These wrappers keep the original parser/*.py files unchanged. Parsers with
hard-coded relative output directories are copied into a per-output staging
folder and executed there so generated JSON stays artifact-local.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable


OUTPUT_NAMES = {
    "fig04": "fig04_lossless_dcn_p99_fct",
    "fig05": "fig05_lossless_ooo_degree",
    "fig06": "fig06_lossless_pfc_pause_duration",
    "tbl04": "tbl04_lossless_avg_egress_queue",
    "fig07": "fig07_lossless_ai_collective_cct",
    "fig08": "fig08_lossless_pfc_incast_degree",
    "fig09": "fig09_lossless_queue_per_pfc_event",
    "fig10": "fig10_lossless_spine_queue_timeseries",
    "tbl05": "tbl05_lossless_spine_pause_balance",
}

TABLE_ORDER = ["ECMP", "ConWeave", "DRILL", "RPS", "AR"]


def default_ns3_root() -> Path:
    return Path(__file__).resolve().parents[3]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--selected-history", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--ns3-root", type=Path, default=default_ns3_root())
    parser.add_argument("--dry-run", action="store_true")


def command_line(cmd: Iterable[object]) -> str:
    return " ".join(str(part) for part in cmd)


def run(cmd: list[object], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    if dry_run:
        print("PARSER_COMMAND", command_line(cmd))
        return
    subprocess.run([str(part) for part in cmd], cwd=cwd, check=True)


def ensure_input(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"ERROR: missing {label}: {path}")


def history_fields(line: str) -> list[str]:
    return line.rstrip("\n").split(",")


def select_history_rows(
    history: Path,
    selected_history: Path,
    predicate: Callable[[list[str]], bool],
    expected: int | None = None,
) -> list[str]:
    ensure_input(history, "history")
    rows = []
    for line in history.read_text(encoding="utf-8").splitlines():
        fields = history_fields(line)
        if len(fields) >= 24 and predicate(fields):
            rows.append(line)
    if expected is not None and len(rows) != expected:
        raise SystemExit(
            f"ERROR: {selected_history} selected {len(rows)} rows; expected {expected}"
        )
    selected_history.parent.mkdir(parents=True, exist_ok=True)
    selected_history.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    return rows


def split_filter(values: list[str]) -> set[str]:
    return {item for value in values for item in value.split(";") if item}


def select_manifest_history(
    manifest: Path,
    history: Path,
    selected_history: Path,
    *,
    figures: set[str] | None = None,
    workloads: set[str] | None = None,
    group_sizes: set[str] | None = None,
    algorithms: set[str] | None = None,
    expected: int | None = None,
) -> list[str]:
    ensure_input(manifest, "manifest")
    ensure_input(history, "history")
    with manifest.open(newline="", encoding="utf-8") as handle:
        manifest_rows = list(csv.DictReader(handle))
    wanted: list[str] = []
    for row in manifest_rows:
        outputs = set(row.get("paper_outputs", "").split(";"))
        if figures and not figures.intersection(outputs):
            continue
        if workloads and row.get("workload") not in workloads:
            continue
        if group_sizes and row.get("group_size") not in group_sizes:
            continue
        if algorithms and row.get("algorithm") not in algorithms:
            continue
        wanted.append(row["config_id"])
    if expected is not None and len(wanted) != expected:
        raise SystemExit(
            f"ERROR: manifest selection for {selected_history} matched {len(wanted)} runs; expected {expected}"
        )
    by_config: dict[str, str] = {}
    for line in history.read_text(encoding="utf-8").splitlines():
        fields = history_fields(line)
        if len(fields) > 1:
            by_config[fields[1]] = line
    missing = [config_id for config_id in wanted if config_id not in by_config]
    if missing:
        raise SystemExit("ERROR: manifest IDs missing from history: " + ", ".join(missing))
    rows = [by_config[config_id] for config_id in wanted]
    selected_history.parent.mkdir(parents=True, exist_ok=True)
    selected_history.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    return rows


def stage_parser(ns3_root: Path, stage_dir: Path, parser_name: str, parser_args: list[object], *, dry_run: bool = False) -> Path:
    parser_src = ns3_root / "parser" / parser_name
    if not parser_src.is_file():
        raise SystemExit(f"ERROR: missing parser backend: {parser_src}")
    parser_dst = stage_dir / "parser" / parser_name
    if dry_run:
        print("STAGE_PARSER", parser_src, "->", parser_dst)
        print("PARSER_COMMAND", command_line(["python3", parser_dst, *parser_args]))
        return stage_dir
    parser_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(parser_src, parser_dst)
    for name in ("mix", "config", "analysis"):
        link = stage_dir / name
        target = ns3_root / name
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(target, link)
    run(["python3", parser_dst, *parser_args], cwd=stage_dir)
    return stage_dir


def copy_one(src: Path, dst: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        print("COPY", src, dst)
        return
    ensure_input(src, "parser output")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_matching(src_dir: Path, pattern: str, dst_dir: Path, *, expected: int | None = None, dry_run: bool = False) -> list[Path]:
    files = sorted(src_dir.glob(pattern))
    if expected is not None and len(files) != expected and not dry_run:
        raise SystemExit(f"ERROR: {src_dir} produced {len(files)} {pattern} files; expected {expected}")
    if dry_run:
        print("COPY_MATCHING", src_dir / pattern, "->", dst_dir)
        return files
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        shutil.copy2(src, dst_dir / src.name)
    return files


def build_table4(input_json: Path, output_dir: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        print("TABLE_COMMAND build_table4", input_json, output_dir)
        return
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    by_scheme = {}
    for series in payload.get("data_series", []):
        summary = (series.get("egress_data") or {}).get("summary") or {}
        if "avg_qlen_bytes" not in summary:
            continue
        avg_bytes = float(summary["avg_qlen_bytes"])
        scheme = series["load_balancing_mode"]
        by_scheme[scheme] = (avg_bytes, avg_bytes / 1024.0)
    missing = [scheme for scheme in TABLE_ORDER if scheme not in by_scheme]
    if missing:
        raise SystemExit("ERROR: missing Table 4 schemes: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "tbl04_lossless_avg_egress_queue.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scheme", "avg_egress_qlen_bytes", "avg_egress_qlen_kb"])
        for scheme in TABLE_ORDER:
            avg_bytes, avg_kb = by_scheme[scheme]
            writer.writerow([scheme, f"{avg_bytes:.6f}", f"{avg_kb:.6f}"])
    md_lines = [
        "| Scheme | Average egress queue length (KB) |",
        "|---|---:|",
    ]
    md_lines.extend(f"| {scheme} | {by_scheme[scheme][1]:.2f} |" for scheme in TABLE_ORDER)
    (output_dir / "tbl04_lossless_avg_egress_queue.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def build_table5(input_dir: Path, output_dir: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        print("TABLE_COMMAND build_table5", input_dir, output_dir)
        return
    files = sorted(input_dir.glob("PFC_SPINE_BALANCE_*.json"))
    if len(files) != 1:
        raise SystemExit(f"ERROR: expected one Table 5 JSON in {input_dir}, found {len(files)}")
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    by_scheme = {}
    for series in payload["data_series"]:
        result = series.get("spine_to_leaf_balance")
        if not result:
            continue
        summary = result["overall_summary"]
        by_scheme[series["load_balancing_mode"]] = {
            "avg_pause_ms": float(summary["mean_of_means_ns"]) / 1_000_000.0,
            "avg_cov": float(summary["mean_cv"]),
            "min_cov": float(summary["min_cv"]),
            "max_cov": float(summary["max_cv"]),
        }
    missing = [scheme for scheme in TABLE_ORDER if scheme not in by_scheme]
    if missing:
        raise SystemExit("ERROR: missing Table 5 schemes: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "tbl05_lossless_spine_pause_balance.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scheme", "avg_pause_ms", "avg_cov", "min_cov", "max_cov"])
        for scheme in TABLE_ORDER:
            row = by_scheme[scheme]
            writer.writerow([
                scheme,
                f'{row["avg_pause_ms"]:.6f}',
                f'{row["avg_cov"]:.6f}',
                f'{row["min_cov"]:.6f}',
                f'{row["max_cov"]:.6f}',
            ])
    md_lines = [
        "| Scheme | Avg. pause (ms) | Avg. CoV | CoV range |",
        "|---|---:|---:|---:|",
    ]
    for scheme in TABLE_ORDER:
        row = by_scheme[scheme]
        md_lines.append(
            f'| {scheme} | {row["avg_pause_ms"]:.2f} | {row["avg_cov"]:.3f} | '
            f'[{row["min_cov"]:.3f}, {row["max_cov"]:.3f}] |'
        )
    (output_dir / "tbl05_lossless_spine_pause_balance.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
