#!/usr/bin/env python3
"""
Fix the trailing BUFFER_SIZE parameter in history_diffbw/all.txt.

For each data line like:
  MM/DD/YY,<sim_id>,...,3000,3000[,<buffer>]
or:
  MM/DD/YY,<sim_id>,...,320,100[,<buffer>]

The script reads mix/output/<sim_id>/config.txt, extracts the BUFFER_SIZE
value, and:
  - appends it if missing
  - replaces it if present but different from the config value
Lines whose config.txt cannot be found are left untouched and reported.
"""

import os
import re
import sys
import shutil

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, "history_diffbw", "all.txt")
OUTPUT_DIR   = os.path.join(SCRIPT_DIR, "output")

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2},")


def read_buffer_size(sim_id: str):
    """Return the BUFFER_SIZE string from mix/output/<sim_id>/config.txt, or None."""
    cfg = os.path.join(OUTPUT_DIR, sim_id, "config.txt")
    if not os.path.isfile(cfg):
        return None
    try:
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if line.startswith("BUFFER_SIZE"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
    except OSError:
        return None
    return None


def normalize(v: str) -> str:
    """Normalize numeric strings so '0.5' == '0.50' when comparing."""
    try:
        return ("%g" % float(v))
    except ValueError:
        return v


def has_trailing_buffer(fields):
    """A trailing buffer-size field is a float (contains '.')."""
    return "." in fields[-1]


def process(dry_run: bool = False):
    if not os.path.isfile(HISTORY_FILE):
        print("ERROR: %s not found" % HISTORY_FILE, file=sys.stderr)
        sys.exit(1)

    with open(HISTORY_FILE) as f:
        lines = f.readlines()

    changed = 0
    missing = []      # sim_ids whose config.txt isn't found
    updates = []      # (lineno, sim_id, old, new)

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if not DATE_RE.match(line):
            continue

        fields = line.split(",")
        if len(fields) < 3:
            continue

        sim_id = fields[1]
        bsz = read_buffer_size(sim_id)
        if bsz is None:
            missing.append((i + 1, sim_id))
            continue

        if has_trailing_buffer(fields):
            old = fields[-1]
            if normalize(old) != normalize(bsz):
                fields[-1] = bsz
                new_line = ",".join(fields)
                lines[i] = new_line + "\n"
                updates.append((i + 1, sim_id, old, bsz, "replace"))
                changed += 1
        else:
            fields.append(bsz)
            new_line = ",".join(fields)
            lines[i] = new_line + "\n"
            updates.append((i + 1, sim_id, "(none)", bsz, "append"))
            changed += 1

    # Report
    for lineno, sim_id, old, new, kind in updates:
        print("line %4d  %s  %-8s  %s -> %s" %
              (lineno, sim_id, kind, old, new))
    if missing:
        print()
        print("WARNING: config.txt not found for %d lines:" % len(missing))
        for lineno, sim_id in missing:
            print("  line %4d  %s" % (lineno, sim_id))

    print()
    print("Total lines changed: %d" % changed)

    if dry_run:
        print("(dry-run: no file was written)")
        return

    if changed:
        backup = HISTORY_FILE + ".bak"
        shutil.copy2(HISTORY_FILE, backup)
        with open(HISTORY_FILE, "w") as f:
            f.writelines(lines)
        print("Backup saved to %s" % backup)
        print("Updated %s" % HISTORY_FILE)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    process(dry_run=dry)
