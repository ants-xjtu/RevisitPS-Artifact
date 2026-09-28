"""JCT in microseconds; each group and repetition stays separate; nearest-rank p99."""
import csv
import math
import statistics


def samples(path, expected=None):
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        if 'jct_us' not in (reader.fieldnames or []):
            raise ValueError(f'Missing jct_us column: {path}')
        values = []
        iterations = []
        for row in reader:
            value = float(row['jct_us'])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'Invalid JCT: {path}')
            values.append(value)
            if 'iter' in row:
                iterations.append(int(row['iter']))
    if not values or expected is not None and len(values) != expected:
        raise ValueError(f'Wrong sample count: {path}: {len(values)}, expected {expected}')
    if iterations and (len(set(iterations)) != len(values) or sorted(iterations) != list(range(len(values)))):
        raise ValueError(f'Invalid iteration sequence: {path}')
    return values


def summarize(values):
    ordered = sorted(values)
    return dict(samples=len(values), mean_us=statistics.mean(values), median_us=statistics.median(values),
                p99_us=ordered[math.ceil(.99 * len(values)) - 1], min_us=ordered[0], max_us=ordered[-1])


def parse_results(run_dir, status):
    import json
    from framework.runner import intact, atomic_json
    rows = []
    for task in status['tasks'].values():
        if task['status'] != 'completed':
            continue
        if not intact(task, run_dir):
            raise ValueError('Data integrity failure: ' + task['task_id'])
        attempt = run_dir / task['attempt']
        config = json.loads((attempt / 'configs/ai.json').read_text())
        for group in config['groups']:
            path = attempt / 'raw' / (group['name'] + '.csv')
            rows.append(dict(task_id=task['task_id'], workload=config['workload'],
                             network_mode=config['network_mode'], algorithm=config['algorithm'],
                             group=group['name'], repeat=task['repeat'],
                             **summarize(samples(path, config['parameters']['iters']))))
    if not rows:
        raise ValueError('No completed AI tasks to parse')
    output = run_dir / 'parsed'
    output.mkdir(exist_ok=True)
    atomic_json(output / 'jct.json', rows)
    with (output / 'jct.csv').open('w') as stream:
        writer = csv.DictWriter(stream, list(rows[0])); writer.writeheader(); writer.writerows(rows)
    return rows
