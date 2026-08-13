#!/usr/bin/env python3
"""Build the lossy packet-drop tables from simulator counters."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from artifact_common import ensure_input, history_fields


DROP_TOTAL_RE = re.compile(r"^\s*-> (?:Up |Down )?Total\s*:\s*(\d+)\s*$")
TRIMMED_RE = re.compile(r"^\s*Packets Trimmed\s*:\s*(\d+)\s*$")
RX_HEADER = "# total_rx_packets,ooo_packets,ooo_rate"


def parse_drop_statistics(path: Path) -> tuple[int, int, int]:
    ensure_input(path, "flow-drop statistics")
    lines = path.read_text(encoding="utf-8").splitlines()
    dropped = sum(
        int(match.group(1))
        for line in lines
        if (match := DROP_TOTAL_RE.match(line))
    )
    received = None
    trimmed = 0
    for line in lines:
        match = TRIMMED_RE.match(line)
        if match:
            trimmed = int(match.group(1))
            break
    for index, line in enumerate(lines[:-1]):
        if line.strip() == RX_HEADER:
            received = int(lines[index + 1].split(",", 1)[0])
            break
    if dropped <= 0:
        raise SystemExit(f"ERROR: no switch drop totals in {path}")
    if received is None or received <= 0:
        raise SystemExit(f"ERROR: no received-packet total in {path}")
    if trimmed > dropped:
        raise SystemExit(f"ERROR: trimmed packets exceed drops in {path}")
    return dropped, received, trimmed


def scheme_label(row: dict[str, str]) -> str:
    algorithm = row["algorithm"]
    recipe = row["recipe"]
    timeout = row["timeout_mode"]
    if algorithm in {"ECMP", "ConWeave"}:
        return f"{algorithm} (NAK+SR)"
    if algorithm != "AR":
        raise SystemExit(f"ERROR: unsupported drop-table algorithm: {algorithm}")
    if "trim" in recipe:
        recovery = "Packet trimming"
    else:
        recovery = "RTO+GBN"
    if timeout == "1":
        recovery += "+Slow Start"
    return f"AR ({recovery})"


def build_lossy_drop_table(
    *,
    table_number: int,
    manifest: Path,
    selected_history: Path,
    ns3_root: Path,
    output_dir: Path,
    table_dir: Path,
    scheme_order: list[str],
    dry_run: bool = False,
) -> None:
    stem = f"tbl{table_number:02d}_lossy_packet_drops"
    if dry_run:
        print("TABLE_COMMAND", stem, selected_history, table_dir)
        return

    ensure_input(manifest, "manifest")
    ensure_input(selected_history, "selected history")
    selected_ids = [
        history_fields(line)[1]
        for line in selected_history.read_text(encoding="utf-8").splitlines()
        if len(history_fields(line)) > 1
    ]
    with manifest.open(newline="", encoding="utf-8") as handle:
        by_config = {
            row["config_id"]: row for row in csv.DictReader(handle)
        }

    rows = []
    for config_id in selected_ids:
        row = by_config.get(config_id)
        if row is None:
            raise SystemExit(f"ERROR: config {config_id} is missing from {manifest}")
        stats = (
            ns3_root / "mix" / "output" / config_id
            / f"{config_id}_out_flow_drop.txt"
        )
        dropped, received, trimmed = parse_drop_statistics(stats)
        # Trimmed headers reach the receiver and are already included in
        # received, while ordinary dropped packets are not.
        observed = received + dropped - trimmed
        rows.append(
            {
                "scheme": scheme_label(row),
                "drop_rate": dropped / observed,
                "drop_rate_percent": 100.0 * dropped / observed,
                "drop_count": dropped,
                "received_packets": received,
                "trimmed_packets": trimmed,
                "observed_packets": observed,
                "config_id": config_id,
            }
        )

    by_scheme = {row["scheme"]: row for row in rows}
    missing = [scheme for scheme in scheme_order if scheme not in by_scheme]
    unexpected = sorted(set(by_scheme) - set(scheme_order))
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise SystemExit(f"ERROR: Table {table_number} schemes: " + "; ".join(details))

    ordered = [by_scheme[scheme] for scheme in scheme_order]
    output_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "paper_output": f"table{table_number}",
                    "drop_rate_definition": (
                        "drops / (received packets + drops - trimmed packets)"
                    ),
                },
                "data_series": ordered,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (table_dir / f"{stem}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["scheme", "drop_rate_percent", "drop_count", "config_id"]
        )
        for row in ordered:
            writer.writerow(
                [
                    row["scheme"],
                    f'{row["drop_rate_percent"]:.6f}',
                    row["drop_count"],
                    row["config_id"],
                ]
            )
    markdown = [
        "| Scheme | Drop Rate | # Drops |",
        "|---|---:|---:|",
        *[
            f'| {row["scheme"]} | {row["drop_rate_percent"]:.2f}% | '
            f'{row["drop_count"]:,} |'
            for row in ordered
        ],
    ]
    (table_dir / f"{stem}.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )
