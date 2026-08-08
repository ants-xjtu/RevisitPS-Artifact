#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def monorepo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")


def run_bazel(target: str, args: list[object], *, dry_run: bool = False) -> None:
    cmd = ["bazel", "run", target, "--", *[str(arg) for arg in args]]
    if dry_run:
        print("PLOT_COMMAND", " ".join(cmd))
        return
    subprocess.run(cmd, cwd=monorepo_root(), check=True)


def copy_file(src: Path, dst: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        print("COPY", src, dst)
        return
    if not src.is_file():
        raise SystemExit(f"ERROR: missing plot output: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_matching(src_dir: Path, pattern: str, dst_dir: Path, prefix: str, *, dry_run: bool = False) -> None:
    if dry_run:
        print("COPY_MATCHING", src_dir / pattern, "->", dst_dir, f"prefix={prefix}")
        return
    matches = sorted(src_dir.glob(pattern))
    if not matches:
        raise SystemExit(f"ERROR: no files matched {src_dir / pattern}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in matches:
        shutil.copy2(src, dst_dir / f"{prefix}_{src.name}")
