#!/usr/bin/env python3
import sys

MSS = 1460

def convert_tcl_to_bytes(fname: str):
    cdf = []
    with open(fname, "r") as f:
        for line in f:
            rec = line.strip().split()
            if len(rec) != 3:
                continue
            mss = float(rec[0])
            prob = float(rec[2])
            size_bytes = round(mss * MSS)
            cdf.append((size_bytes, prob * 100))  # 转换成百分比
    return cdf

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <cdf_file>")
        sys.exit(1)

    cdf_list = convert_tcl_to_bytes(sys.argv[1])
    for size, prob in cdf_list:
        print(f"{size:<8d}\t{prob:.2f}")
