#!/usr/bin/python3
"""
Regroup per-bufsz JSONs into the format expected by
main/plot_sample/plot_dcn_fct_lb_recovery_grouped.py, one file per
(topo_family, flow_control, LB mode, loss_recovery).

Inputs   : parser/json-data-fct-per-bufsz/*.json
Filters  :
    recovery_mechanism in {RTO+GBN+Now, RTO+GBN+slowstart}
    (bandwidth, buffer_size) in:
        (100G, 0.50)
        (400G, 0.32), (400G, 0.44), (400G, 1.92)
    topology family in {fattree, leafspine}

Output layout (one file per group):
{
  "group": {"load_balancing_mode": "...", "recovery_mechanism": "..."},
  "variants": [
    {
      "source_file": "<topo>_<bw>_OS<k>__<fc>__bufsz_<bufsz>.json",
      "buffer_size": "<bufsz>",
      "data_series": [
          {"buffer_size": "...", "avg_fct_slowdown": [...],
           "p99_fct_slowdown": [...], "flow_size_buckets_bytes": [...], ...}
      ]
    }, ...
  ]
}

The plotter regex on source_file:
    ^(.*)_(100G|400G)_OS\\d+__(Lossless|Lossy)__bufsz_([0-9.]+)\\.json$
so we reconstruct source_file from the original topology/fc/bufsz.
"""

import os
import re
import json
import shutil
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SRC_DIR    = os.path.join(SCRIPT_DIR, "json-data-fct-per-bufsz")
DST_DIR    = os.path.join(SCRIPT_DIR, "json-rto-gbn-compare")

RECOVERY_KEEP = {"RTO+GBN+Now", "RTO+GBN+slowstart"}

# Normalized buffer-size sets per bandwidth (strings as stored in history).
BW_BUFSZ = {
    "100G": {"0.5", "0.50"},
    "400G": {"0.32", "0.44", "1.92"},
}

TOPO_RE = re.compile(r"^(.*)_(100G|200G|400G)_OS\d+$")


def topo_family(topo: str) -> str:
    if topo.startswith("fat_"):
        return "fattree"
    if topo.startswith("leaf_spine") or topo.startswith("leafspine"):
        return "leafspine"
    return ""


def topo_bandwidth(topo: str) -> str:
    m = TOPO_RE.match(topo)
    if m:
        return m.group(2)
    for bw in ("400G", "200G", "100G"):
        if bw in topo:
            return bw
    return ""


def bufsz_allowed(bw: str, bufsz: str) -> bool:
    return bw in BW_BUFSZ and bufsz in BW_BUFSZ[bw]


def normalize_bufsz(bufsz: str) -> str:
    """Plot script's BUFFER_STYLES keys are '0.31','0.32','0.44','0.50'.
    Normalize '0.5' -> '0.50' so styles line up. Leave others as-is."""
    try:
        f = float(bufsz)
    except ValueError:
        return bufsz
    if bufsz == "0.5":
        return "0.50"
    return bufsz


def sanitize(s: str) -> str:
    return s.replace("+", "-plus-").replace("/", "_")


def main():
    if os.path.isdir(DST_DIR):
        shutil.rmtree(DST_DIR)
    os.makedirs(DST_DIR, exist_ok=True)

    # (family, fc, lb, rec) -> {(topo, bufsz): variant_dict}
    groups = defaultdict(dict)

    for name in sorted(os.listdir(SRC_DIR)):
        if not name.endswith(".json"):
            continue
        src = os.path.join(SRC_DIR, name)
        with open(src) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"Skip (bad JSON): {name}")
                continue

        meta = data.get("metadata", {})
        topo  = meta.get("topology", "")
        fc    = meta.get("flow_control", "")
        bufsz = meta.get("buffer_size", "")

        family = topo_family(topo)
        bw     = topo_bandwidth(topo)
        if not family or not bw:
            continue
        if not bufsz_allowed(bw, bufsz):
            continue

        bufsz_n = normalize_bufsz(bufsz)
        source_file = f"{topo}__{fc}__bufsz_{bufsz_n}.json"

        for s in data.get("data_series", []):
            rec = s.get("recovery_mechanism")
            if rec not in RECOVERY_KEEP:
                continue
            lb = s.get("load_balancing_mode", "unknown")
            gkey = (family, fc, lb, rec)
            vkey = (topo, bufsz_n)

            variants = groups[gkey]
            if vkey not in variants:
                variants[vkey] = {
                    "source_file": source_file,
                    "buffer_size": bufsz_n,
                    "data_series": [],
                }

            series_out = dict(s)
            series_out["buffer_size"] = bufsz_n
            variants[vkey]["data_series"].append(series_out)

    written = 0
    for (family, fc, lb, rec), variants in sorted(groups.items()):
        if not variants:
            continue

        def _vsort(item):
            (topo, bufsz) = item[0]
            bw = topo_bandwidth(topo)
            try:
                bw_rank = int(bw.rstrip("G"))
            except ValueError:
                bw_rank = 0
            try:
                bf_rank = float(bufsz)
            except ValueError:
                bf_rank = float("inf")
            return (bw_rank, bf_rank, topo)

        out = {
            "group": {
                "load_balancing_mode": lb,
                "recovery_mechanism":  rec,
                "topo_family":         family,
                "flow_control":        fc,
            },
            "variants": [v for _, v in sorted(variants.items(), key=_vsort)],
        }

        fname = (f"TOPO_{family}_FC_{fc}"
                 f"_LB_{sanitize(lb)}_REC_{sanitize(rec)}.json")
        path = os.path.join(DST_DIR, fname)
        with open(path, "w") as f:
            json.dump(out, f, indent=4)
        written += 1
        n_series = sum(len(v["data_series"]) for v in out["variants"])
        print(f"-> {os.path.relpath(path, SCRIPT_DIR)}  "
              f"({len(out['variants'])} variants, {n_series} series)")

    print()
    print(f"Done. {written} JSON files written to "
          f"{os.path.relpath(DST_DIR, SCRIPT_DIR)}/")


if __name__ == "__main__":
    main()
