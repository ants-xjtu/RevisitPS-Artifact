#!/usr/bin/env python3
"""
Split mix/history_diffbw/all.txt into per-(topology, flow_control, buffer_size)
files.

Each entry in all.txt is a 3-line block separated by a blank line:
    <CSV data line>   # fields[10]=pfc (1=Lossless, else Lossy),
                      # fields[15]=topo, fields[24]=buffer_size
    ./waf --run '... <id>/config.txt' > ...
    ./waf --run ... gdb --args ... <id>/config.txt

Output files are written to:
    mix/history_diffbw/split/<topo>__<Lossless|Lossy>__bufsz_<buffer_size>.txt
preserving the original 3-line block format (blank line between blocks).
"""

import os
import re
import sys
from collections import defaultdict

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, "history_diffbw", "all.txt")
OUT_DIR      = os.path.join(SCRIPT_DIR, "history_diffbw", "split")

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2},")


def sanitize(s: str) -> str:
    # keep filenames tame
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def iter_blocks(path):
    """Yield (data_line, [follow_lines...]) blocks from the history file.

    A block starts at a line matching DATE_RE and ends at the next such line
    or at EOF. Blank lines between blocks are skipped; blank lines / extra
    content between the data line and the next block are preserved as
    follow_lines (usually the two ./waf commands).
    """
    with open(path) as f:
        lines = f.readlines()

    i = 0
    n = len(lines)
    while i < n:
        if DATE_RE.match(lines[i]):
            data_line = lines[i].rstrip("\n")
            follow = []
            j = i + 1
            while j < n and not DATE_RE.match(lines[j]):
                follow.append(lines[j].rstrip("\n"))
                j += 1
            # Trim trailing blank lines on the block
            while follow and follow[-1].strip() == "":
                follow.pop()
            yield data_line, follow
            i = j
        else:
            i += 1


def main():
    if not os.path.isfile(HISTORY_FILE):
        print(f"ERROR: {HISTORY_FILE} not found", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    # bucket: (topo, flow_control, buffer_size) -> list of block-text strings
    buckets = defaultdict(list)
    skipped = 0

    for data_line, follow in iter_blocks(HISTORY_FILE):
        fields = data_line.split(",")
        if len(fields) < 25:
            skipped += 1
            continue
        try:
            pfc = int(fields[10])
        except ValueError:
            skipped += 1
            continue
        topo         = fields[15]
        buffer_size  = fields[24]
        flow_control = "Lossless" if pfc == 1 else "Lossy"

        block = data_line + "\n"
        for fl in follow:
            block += fl + "\n"
        block += "\n"   # trailing blank line between blocks

        buckets[(topo, flow_control, buffer_size)].append(block)

    # Write out
    for (topo, fc, bufsz), blocks in sorted(buckets.items()):
        fname = f"{sanitize(topo)}__{sanitize(fc)}__bufsz_{sanitize(bufsz)}.txt"
        fpath = os.path.join(OUT_DIR, fname)
        with open(fpath, "w") as f:
            f.write("".join(blocks))
        print(f"{len(blocks):4d} entries -> {fpath}")

    print()
    print(f"Total buckets: {len(buckets)}")
    if skipped:
        print(f"Skipped {skipped} entries with <25 CSV fields (no buffer_size).")


if __name__ == "__main__":
    main()
