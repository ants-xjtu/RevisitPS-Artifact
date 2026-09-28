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


def parse_results(run_dir, status):
    import csv
    import json
    from framework.runner import intact, yaml_read, atomic_json
    from experiments.dcn_workload.scripts.parse import parse_fct, summarize
    from experiments.dcn_workload.scripts.fct_statistics import summarize_size_buckets
    from experiments.dcn_workload.scripts.plot_throughput import read_intervals, aggregate_windows
    output = run_dir / 'parsed'
    output.mkdir(exist_ok=True)
    summaries, throughput, size_buckets = [], [], []
    if not any(task['status'] == 'completed' for task in status['tasks'].values()):
        raise ValueError('No completed tasks to parse')
    for task in status['tasks'].values():
        if task['status'] != 'completed':
            continue
        if not intact(task, run_dir):
            raise ValueError(f'Data integrity failure: {task["task_id"]}')
        attempt = run_dir / task['attempt']
        runtime = yaml_read(attempt / 'configs/runtime.yaml')
        spec = runtime['artifact']['experiment']
        common = dict(task_id=task['task_id'], experiment=spec['id'], group=spec['group'],
                      algorithm=spec['algorithm'], repeat=task['repeat'])
        if spec['metric'] == 'fct':
            records = []
            for path in sorted((attempt / 'raw').glob('*.sender.log.csv')):
                rows, counts = parse_fct(path)
                if any(counts[key] for key in ('incomplete', 'nonpositive', 'malformed')):
                    raise ValueError(f'Invalid FCT: {path}')
                records.extend(rows)
            if not records:
                raise ValueError('No FCT samples')
            for row in summarize(records):
                summaries.append(common | row)
            if spec["group"] in ("lossless", "lossy"):
                for row in summarize_size_buckets(records):
                    size_buckets.append(common | row)
        else:
            series = [read_intervals(path) for path in sorted((attempt / 'raw').glob('*.sender.log'))]
            measurement = runtime['artifact']['measurement']
            # Starts are coordinated but not strictly simultaneous. Preserve measured
            # launch offsets in the common orchestrator time axis.
            starts = json.loads((attempt / 'raw/starts.json').read_text())
            origin = min(item['started'] for item in starts)
            offsets = {item['connection']: item['started'] - origin for item in starts}
            paths = sorted((attempt / 'raw').glob('*.sender.log'))
            for path, rows in zip(paths, series):
                offset = offsets[path.name]
                for row in rows:
                    row['start'] += offset
                    row['end'] += offset
            begin = max(offsets.values()) + measurement['warmup_seconds']
            end = min(rows[-1]['end'] for rows in series)
            for row in aggregate_windows(series, begin, end):
                throughput.append(common | row)
    atomic_json(output / 'figure2-buckets.json', size_buckets)
    atomic_json(output / 'fct.json', summaries)
    atomic_json(output / 'throughput.json', throughput)
    for name, rows in [('fct', summaries), ('throughput', throughput), ('figure2-buckets', size_buckets)]:
        if rows:
            with (output / (name + '.csv')).open('w') as stream:
                writer = csv.DictWriter(stream, list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
