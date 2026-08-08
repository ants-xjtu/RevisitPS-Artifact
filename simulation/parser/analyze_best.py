#!/usr/bin/env python3
"""
遍历 JSON 文件，
FCT 模式对每个文件的 data_series 找出 avg_fct_slowdown 均值最小 和 p99_fct_slowdown 均值最小的条目，
JCT 模式对每个文件的 data_series 找出 points[*].jct_us 均值最小的条目，
并计算它相对其他每个条目好了百分之多少（值越小越好，所以 improvement = (other - best) / other * 100%）。
"""

import json
import os
import sys
import glob
import argparse


def entry_label(entry, metadata=None):
    metadata = metadata or {}
    return (
        f"lb={entry.get('load_balancing_mode','?')}, "
        f"rec={entry.get('recovery_mechanism','?')}, "
        f"to={entry.get('timeout_mode','?')}, "
        f"cc={entry.get('congestion_control','?')}, "
        f"win={entry.get('window_size', metadata.get('window_size', '?'))}"
    )


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def pct_better(best_value, other_value):
    return (other_value - best_value) / other_value * 100 if other_value else float("nan")


def is_trimming_entry(entry):
    for key in ("load_balancing_mode", "recovery_mechanism", "timeout_mode", "congestion_control", "label"):
        value = entry.get(key)
        if isinstance(value, str) and "trim" in value.lower():
            return True
    return False


def filter_trimming(series):
    kept = [s for s in series if not is_trimming_entry(s)]
    return kept, len(series) - len(kept)


def analyze_fct(path, series, metadata):
    series, skipped = filter_trimming(series)
    if not series:
        print(f"[skip] {path} 排除 trimming 后没有 data_series")
        return

    rows = []
    for s in series:
        rows.append({
            "label": entry_label(s, metadata),
            "avg": mean(s.get("avg_fct_slowdown", [])),
            "p99": mean(s.get("p99_fct_slowdown", [])),
        })

    best_avg = min(rows, key=lambda r: r["avg"])
    best_p99 = min(rows, key=lambda r: r["p99"])

    print("=" * 90)
    print(f"File: {os.path.basename(path)}")
    if skipped:
        print(f"Filtered trimming series: {skipped}")
    print("-" * 90)

    print(f"[AVG FCT slowdown 最优] {best_avg['label']}  mean(avg)={best_avg['avg']:.4f}")
    for r in rows:
        if r is best_avg:
            continue
        diff = r["avg"] - best_avg["avg"]
        pct = pct_better(best_avg["avg"], r["avg"])
        print(f"  vs {r['label']:70s} mean(avg)={r['avg']:.4f}  "
              f"best 比它低 {diff:+.4f} ({pct:+.2f}%)")

    print("-" * 90)
    print(f"[P99 FCT slowdown 最优] {best_p99['label']}  mean(p99)={best_p99['p99']:.4f}")
    for r in rows:
        if r is best_p99:
            continue
        diff = r["p99"] - best_p99["p99"]
        pct = pct_better(best_p99["p99"], r["p99"])
        print(f"  vs {r['label']:70s} mean(p99)={r['p99']:.4f}  "
              f"best 比它低 {diff:+.4f} ({pct:+.2f}%)")
    print()


def analyze_jct(path, series, metadata):
    series, skipped = filter_trimming(series)
    if not series:
        print(f"[skip] {path} 排除 trimming 后没有 data_series")
        return

    rows = []
    for s in series:
        jcts = [p.get("jct_us") for p in s.get("points", [])]
        ideals = [p.get("ideal_jct_us") for p in s.get("points", [])]
        rows.append({
            "label": entry_label(s, metadata),
            "jct": mean(jcts),
            "ideal": mean(ideals),
        })

    best_jct = min(rows, key=lambda r: r["jct"])

    print("=" * 90)
    print(f"File: {os.path.basename(path)}")
    if skipped:
        print(f"Filtered trimming series: {skipped}")
    print("-" * 90)

    ideal_part = ""
    if best_jct["ideal"] == best_jct["ideal"]:
        overhead = (best_jct["jct"] - best_jct["ideal"]) / best_jct["ideal"] * 100 if best_jct["ideal"] else float("nan")
        ideal_part = f"  mean(ideal)={best_jct['ideal']:.4f} us  over ideal={overhead:+.2f}%"

    print(f"[JCT 最优] {best_jct['label']}  mean(jct)={best_jct['jct']:.4f} us{ideal_part}")
    for r in rows:
        if r is best_jct:
            continue
        diff = r["jct"] - best_jct["jct"]
        pct = pct_better(best_jct["jct"], r["jct"])
        print(f"  vs {r['label']:70s} mean(jct)={r['jct']:.4f} us  "
              f"best 比它低 {diff:+.4f} us ({pct:+.2f}%)")
    print()


def analyze_one(path, mode):
    with open(path) as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    series = data.get("data_series", [])
    if not series:
        print(f"[skip] {path} 没有 data_series")
        return

    if mode == "jct":
        analyze_jct(path, series, metadata)
    else:
        analyze_fct(path, series, metadata)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "paths", nargs="*",
        help="JSON 文件或目录。默认 FCT 扫描 json-data=fct/*.json，JCT 扫描 json-data-400G-0p32-ai/*.json",
    )
    ap.add_argument(
        "--mode",
        choices=["fct", "jct"],
        default="fct",
        help="分析模式：fct 分析 avg/p99 FCT slowdown；jct 分析 points[*].jct_us",
    )
    args = ap.parse_args()

    targets = []
    if args.paths:
        for p in args.paths:
            if os.path.isdir(p):
                targets.extend(sorted(glob.glob(os.path.join(p, "*.json"))))
            else:
                targets.append(p)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        default_dir = "json-data-400G-0p32-ai" if args.mode == "jct" else "json-data=fct"
        targets = sorted(glob.glob(os.path.join(here, default_dir, "*.json")))

    if not targets:
        print("未找到任何 JSON 文件", file=sys.stderr)
        sys.exit(1)

    for p in targets:
        analyze_one(p, args.mode)


if __name__ == "__main__":
    main()
