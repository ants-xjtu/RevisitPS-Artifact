#!/usr/bin/env python3
"""
For each row in an *_out_fct.txt file, if the last column (slowstart flag)
is > 0, set the 3rd-from-last column (measured FCT) to 2 * the 2nd-from-last
column (ideal FCT). All other rows pass through unchanged.

Expected row layout (9 whitespace-separated fields):
    ... fct_measured ideal_fct slowstart_flag
        (col -3)     (col -2)  (col -1)

Usage:
    fix_slowstart_fct.py <fct_file> [-o OUT] [--in-place]
"""

import argparse
import os
import shutil
import sys


def fix_line(line: str) -> str:
    stripped = line.rstrip("\n")
    if not stripped.strip():
        return line
    fields = stripped.split()
    if len(fields) < 3:
        return line
    try:
        slowstart = float(fields[-1])
    except ValueError:
        return line
    if slowstart <= 0:
        return line
    try:
        ideal = float(fields[-2])
    except ValueError:
        return line

    new_fct = ideal * 2
    # Preserve integer formatting if the source looked integral.
    fields[-3] = str(int(new_fct)) if new_fct.is_integer() else repr(new_fct)
    return " ".join(fields) + ("\n" if line.endswith("\n") else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fct_file", help="Path to *_out_fct.txt")
    ap.add_argument("-o", "--output", default=None,
                    help="Output file (default: <input>.fixed)")
    ap.add_argument("--in-place", action="store_true",
                    help="Overwrite input (original saved as <input>.bak)")
    args = ap.parse_args()

    src = args.fct_file
    if not os.path.isfile(src):
        print(f"ERROR: not a file: {src}", file=sys.stderr)
        sys.exit(1)

    if args.in_place:
        dst = src + ".tmp"
    else:
        dst = args.output or (src + ".fixed")

    n_total = 0
    n_fixed = 0
    with open(src) as fin, open(dst, "w") as fout:
        for line in fin:
            n_total += 1
            new_line = fix_line(line)
            if new_line != line:
                n_fixed += 1
            fout.write(new_line)

    if args.in_place:
        bak = src + ".bak"
        shutil.copy2(src, bak)
        os.replace(dst, src)
        print(f"Rewrote {src} in place (backup at {bak})")
    else:
        print(f"Wrote: {dst}")

    print(f"Scanned {n_total} lines, modified {n_fixed}.")


if __name__ == "__main__":
    main()
