#!/usr/bin/env python3
"""Shared helpers for lossless artifact plot wrappers.

The wrappers live in a new monorepo directory and keep plot_sample unchanged.
They call the existing Bazel plotting targets, then copy/rename outputs into
artifact-local figure names.
"""

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


def first_pdf(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise SystemExit(f"ERROR: no PDF matched {directory / pattern}")
    return matches[0]


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
