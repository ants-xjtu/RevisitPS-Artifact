"""Pure parsing of the pinned fork's --trace_log CSV (CPU cycles / MHz = us).

FCT is completion minus posting for the same indexed record. Overlapping records
are retained; subtracting the previous completion would instead measure service
spacing. The fork records CQ completions in poll order, a source-level limitation
for multiple QPs; no unverified per-QP reordering is inferred here.
"""
import csv
import json
import math
from pathlib import Path
import click
import numpy as np
import pandas as pd

THRESHOLD = 60 * 1024


def parse_fct(path, expected_sizes=None):
    records, counts = [], dict(total=0, valid=0, incomplete=0, nonpositive=0, malformed=0)
    with open(path) as source:
        lines = iter(source)
        for line in lines:
            if line.strip() == 'size,start_time,end_time':
                break
        else:
            raise ValueError(f'{path}: missing FCT header')
        for line in lines:
            if not line.strip() or line.strip().startswith('---'):
                continue
            index = counts['total']
            counts['total'] += 1
            try:
                size, start, end = map(float, next(csv.reader([line])))
                if not all(math.isfinite(x) for x in (size, start, end)) or size <= 0 or int(size) != size:
                    raise ValueError('invalid size/timestamp')
                if expected_sizes is not None and (index >= len(expected_sizes) or int(size) != expected_sizes[index]):
                    raise ValueError('trace size/identity mismatch')
                if end == 0 or start == 0:
                    counts['incomplete'] += 1
                elif end <= start:
                    counts['nonpositive'] += 1
                else:
                    records.append(dict(flow_id=index, size=int(size), start_time_us=start,
                                        end_time_us=end, fct=end-start, source=Path(path).name))
                    counts['valid'] += 1
            except (ValueError, TypeError):
                counts['malformed'] += 1
    if expected_sizes is not None:
        counts['incomplete'] += max(0, len(expected_sizes) - counts['total'])
    return records, counts


def summarize(records):
    result = []
    for name, subset in [('all', records), ('small', [r for r in records if r['size'] < THRESHOLD]),
                         ('large', [r for r in records if r['size'] >= THRESHOLD])]:
        values = [r['fct'] for r in subset]
        result.append(dict(size_class=name, samples=len(values),
                           mean_us=float(np.mean(values)) if values else None,
                           p99_us=float(np.percentile(values, 99)) if values else None))
    return result


def _process_single_file(path):
    try:
        records, counts = parse_fct(path)
        if counts['incomplete'] or counts['nonpositive'] or counts['malformed']:
            raise ValueError(str(counts))
        return pd.DataFrame(records), None
    except Exception as exc:
        return None, str(exc)


def process_and_merge(input_dir, output_file='merged.csv', max_workers=None):
    files = sorted(Path(input_dir).glob('*.sender.log.csv'))
    if not files:
        files = sorted(Path(input_dir).glob('*.log'))
    if not files:
        raise ValueError('No FCT logs')
    frames = []
    for path in files:
        frame, error = _process_single_file(path)
        if error:
            raise ValueError(error)
        frames.append(frame)
    pd.concat(frames, ignore_index=True).to_csv(output_file, index=False)


@click.command()
def analysis_fct(test_conf_parser):
    conf = test_conf_parser.get().applications.analysis
    output = Path(conf.output_folder)
    output.mkdir(parents=True, exist_ok=True)
    process_and_merge(conf.input_folder, output / 'merged.csv')
    records = pd.read_csv(output / 'merged.csv').to_dict('records')
    (output / 'stats.json').write_text(json.dumps(summarize(records), indent=2))
