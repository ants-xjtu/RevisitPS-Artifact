"""Time-weighted windows for the pinned fork's infinite-mode BW output.

Rows are bytes, iterations, elapsed seconds, interval average Gbit/s. The
third column of a finite-duration upstream report is NOT a timestamp.
"""
import math
from pathlib import Path
import click
import pandas as pd


def read_intervals(path):
    rows, previous, header = [], 0.0, False
    for line in Path(path).read_text().splitlines():
        if line.strip().startswith('#bytes'):
            if 'Time[sec]' not in line or 'Gb/sec' not in line:
                raise ValueError(f'{path}: not a pinned-fork Gbit/s interval report')
            header = True
            continue
        tokens = line.split()
        if not header or len(tokens) != 4 or not tokens[0].isdigit():
            continue
        _, _, end, rate = map(float, tokens)
        if not math.isfinite(end) or not math.isfinite(rate) or end <= previous or rate < 0:
            raise ValueError(f'{path}: invalid or nonmonotonic bandwidth record')
        rows.append(dict(start=previous, end=end, gbps=rate))
        previous = end
    if not rows:
        raise ValueError(f'{path}: no interval bandwidth data')
    return rows


def window_average(rows, start, end):
    covered, weighted = 0.0, 0.0
    for row in rows:
        overlap = max(0, min(end, row['end']) - max(start, row['start']))
        covered += overlap
        weighted += overlap * row['gbps']
    if end <= start or abs(covered - (end - start)) > 0.002:
        raise ValueError('Bandwidth window has missing or overlapping coverage')
    return weighted / covered


def aggregate_windows(series, start, end, window=1):
    output = []
    cursor = start
    while cursor < end:
        right = min(end, cursor + window)
        output.append(dict(time_s=cursor, end_s=right,
                           gbps=sum(window_average(rows, cursor, right) for rows in series)))
        cursor = right
    return output


def load_data(path):
    return pd.DataFrame([{'Time[sec]': r['end'], 'BW_Gb_s': r['gbps']} for r in read_intervals(path)])


def generate_avg_csv(root_folder, output):
    series = [read_intervals(path) for path in sorted(Path(root_folder).glob('*.sender.log'))]
    if not series:
        raise ValueError('No sender bandwidth logs')
    end = min(rows[-1]['end'] for rows in series)
    records = aggregate_windows(series, 0, math.floor(end))
    Path(output).mkdir(parents=True, exist_ok=True)
    dest = Path(output) / 'total.csv'
    pd.DataFrame(records).to_csv(dest, index=False)
    return [str(dest)]


@click.command()
def plot_throughput(test_conf_parser):
    conf = test_conf_parser.get().applications.plot
    generate_avg_csv(conf.input_folder, conf.output_folder)
