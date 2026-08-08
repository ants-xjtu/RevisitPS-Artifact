#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Plot per-QP sending rate over time for the N longest-lived flows.

Input file format (produced by main.cc's monitor_qp_rate):
    time_ns node_id sip dip sport dport pg send_gbps target_gbps flow_id

Usage:
    python3 plot_qp_rate_top10.py --rate_file path/to/xxx_out_rate.txt
    python3 plot_qp_rate_top10.py --rate_file ... --output rate_top10.pdf \
                                  --metric send --topn 10 --ymax 100
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")  # headless, thread-safe
import matplotlib.pyplot as plt
import pandas as pd


COLUMNS = [
    "time_ns", "node_id", "sip", "dip",
    "sport", "dport", "pg",
    "send_gbps", "target_gbps", "flow_id",
]

QP_KEY = ["node_id", "sip", "dip", "sport", "dport", "pg"]

# sip/dip stay as strings (hex); everything else gets typed up front so the C
# CSV engine can do zero-copy parsing (much faster than post-hoc to_numeric).
DTYPES = {
    "time_ns": "int64",
    "node_id": "int32",
    "sip": "string",
    "dip": "string",
    "sport": "int32",
    "dport": "int32",
    "pg": "int32",
    "send_gbps": "float32",
    "target_gbps": "float32",
    "flow_id": "int32",
}


def load_rate_file(path: str, drop_negative: bool = True) -> pd.DataFrame:
    """Read rate file with the fast C engine; optionally drop GBN-induced negatives."""
    df = pd.read_csv(
        path,
        delim_whitespace=True,
        header=0,
        names=COLUMNS,
        comment="#",
        engine="c",
        dtype=DTYPES,
        on_bad_lines="skip",
    )
    if drop_negative:
        # GBN can rewind snd_nxt between samples -> negative rate. Drop those rows.
        df = df[(df["send_gbps"] >= 0) & (df["target_gbps"] >= 0)]
    return df


def pick_longest_lived(df: pd.DataFrame, topn: int) -> list:
    """Return list of QP keys (tuples) for the top-N longest-lived flows."""
    grp = df.groupby(QP_KEY, sort=False)["time_ns"]
    lifespan = (grp.max() - grp.min()).sort_values(ascending=False)
    return list(lifespan.head(topn).index)


def pick_rank_range(df: pd.DataFrame, start: int, end: int) -> list:
    """Return QP keys ranked [start, end] (1-indexed, inclusive) by lifespan."""
    grp = df.groupby(QP_KEY, sort=False)["time_ns"]
    lifespan = (grp.max() - grp.min()).sort_values(ascending=False)
    return list(lifespan.iloc[start - 1:end].index)


def parse_rank_range(spec: str) -> tuple:
    """Parse 'A-B' (1-indexed, inclusive). 'N' alone means '1-N'."""
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        start, end = int(a), int(b)
    else:
        start, end = 1, int(spec)
    if start < 1 or end < start:
        raise ValueError(f"invalid rank range: {spec!r}")
    return start, end


def flow_label(key) -> str:
    node_id, sip, dip, sport, dport, pg = key
    return f"n{node_id} {sip}:{sport}->{dip}:{dport} pg{pg}"


def plot_rate(df: pd.DataFrame, keys, metric: str, output: str,
              title: str, ymax: float = None, smooth: int = 1) -> None:
    col = "send_gbps" if metric == "send" else "target_gbps"

    # Restrict to only the rows we plot — one indexed lookup instead of N mask scans.
    key_set = set(keys)
    df_small = df[df[QP_KEY].apply(tuple, axis=1).isin(key_set)]
    grouped = df_small.groupby(QP_KEY, sort=False)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    colormap = plt.get_cmap("tab10")

    for idx, key in enumerate(keys):
        try:
            sub = grouped.get_group(key).sort_values("time_ns")
        except KeyError:
            continue
        t_ms = sub["time_ns"].to_numpy() / 1e6
        series = sub[col]
        if smooth and smooth > 1:
            # center=True keeps the smoothed curve aligned with original time;
            # min_periods=1 preserves the edges so the curve spans the full range.
            series = series.rolling(window=smooth, min_periods=1, center=True).mean()
        y = series.to_numpy()
        ax.plot(
            t_ms, y,
            label=flow_label(key),
            color=colormap(idx % 10),
            linewidth=1.2,
            alpha=0.9,
        )

    ax.set_xlabel("Time (ms)")
    ax.set_ylabel(f"{'Sent' if metric == 'send' else 'Target'} rate (Gb/s)")
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.4)
    if ymax is not None:
        ax.set_ylim(0, ymax)
    ax.legend(loc="upper right", fontsize=7, ncol=1, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)
    print(f"[ok] saved {output}")


def main():
    ap = argparse.ArgumentParser(description="Plot rate-over-time for longest-lived QPs")
    ap.add_argument("--rate_file", required=True, help="path to *_out_rate.txt")
    ap.add_argument("--output", default=None)
    ap.add_argument("--topn", type=int, default=10)
    ap.add_argument("--range", dest="rank_range", default=None,
                    help="rank range 'A-B' (1-indexed, inclusive); overrides --topn")
    ap.add_argument("--metric", choices=["send", "target"], default="send")
    ap.add_argument("--ymax", type=float, default=100.0,
                    help="y-axis upper bound in Gb/s; use 0 to disable (default: 100)")
    ap.add_argument("--keep_negative", action="store_true",
                    help="keep negative rate samples (default: drop, since GBN rewinds snd_nxt)")
    ap.add_argument("--smooth", type=int, default=1,
                    help="rolling-mean window in samples (1 disables, default: 1)")
    args = ap.parse_args()

    df = load_rate_file(args.rate_file, drop_negative=not args.keep_negative)
    if df.empty:
        raise SystemExit(f"no data in {args.rate_file}")

    if args.rank_range:
        start, end = parse_rank_range(args.rank_range)
        keys = pick_rank_range(df, start, end)
        rank_tag = f"rank{start}-{end}"
        rank_desc = f"Rank {start}-{start + len(keys) - 1} longest-lived QPs"
    else:
        keys = pick_longest_lived(df, args.topn)
        rank_tag = f"top{args.topn}"
        rank_desc = f"Top-{len(keys)} longest-lived QPs"
    print(f"[info] {len(df)} rows, {df.groupby(QP_KEY).ngroups} unique QPs")

    out = args.output
    if out is None:
        base, _ = os.path.splitext(args.rate_file)
        out = f"{base}_{rank_tag}_{args.metric}.pdf"

    title = f"{rank_desc} — {args.metric} rate"
    if args.smooth and args.smooth > 1:
        title += f" (smooth={args.smooth})"
    ymax = args.ymax if args.ymax and args.ymax > 0 else None
    plot_rate(df, keys, args.metric, out, title, ymax=ymax, smooth=args.smooth)


if __name__ == "__main__":
    main()
