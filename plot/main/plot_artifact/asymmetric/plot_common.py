#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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


def clear_matching(directory: Path, pattern: str, *, dry_run: bool = False) -> None:
    if dry_run:
        print("REMOVE_MATCHING", directory / pattern)
        return
    for path in directory.glob(pattern):
        if path.is_file():
            path.unlink()


def first_matching(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise SystemExit(f"ERROR: no file matched {directory / pattern}")
    return matches[0]


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


@contextmanager
def temporary_workdir(label: str, *, dry_run: bool = False) -> Iterator[Path]:
    if dry_run:
        yield Path("/tmp") / f"revisitps-plot-{label}"
        return
    with tempfile.TemporaryDirectory(prefix=f"revisitps-plot-{label}-") as temp_dir:
        yield Path(temp_dir)


@contextmanager
def temporary_input_dir(
    input_dir: Path, label: str, *, dry_run: bool = False
) -> Iterator[Path]:
    with temporary_workdir(label, dry_run=dry_run) as workdir:
        staged = workdir / "input"
        if not dry_run:
            if not input_dir.is_dir():
                raise SystemExit(f"ERROR: missing plot input directory: {input_dir}")
            shutil.copytree(input_dir, staged)
        yield staged
