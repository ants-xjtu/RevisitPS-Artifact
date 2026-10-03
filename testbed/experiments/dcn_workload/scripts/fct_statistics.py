"""Historical 09cf327 size/FCT interleaving and discrete bucket percentiles."""
from collections import defaultdict
import hashlib
import math
import numpy as np

ALGORITHMS = ('ECMP', 'RPS', 'BigSwitch')
BUCKETS = 19


def summarize_size_buckets(records, buckets=BUCKETS):
    by_size = defaultdict(list)
    for row in records:
        by_size[row['size']].append(max(1., row['fct']))
    # Match parse_fct.py: sort FCTs within each size and flatten 100
    # round-robin sub-buckets. The old >400 cutoff was commented out.
    ordered = []
    for size in sorted(by_size):
        values = sorted(by_size[size])
        width = min(100, len(values))
        for offset in range(width):
            ordered.extend((size, value) for value in values[offset::width])
    if len(ordered) < buckets:
        raise ValueError(f'Need at least {buckets} valid flows for Figure 2')
    # Per-bucket identities differ under historical latency-based interleaving.
    # Compare the complete input identity set instead of requiring identical
    # members in each bucket.
    identities = '\n'.join(sorted(f"{r['source']}:{r['flow_id']}:{r['size']}" for r in records))
    input_hash = hashlib.sha256(identities.encode()).hexdigest()
    result = []
    for index in range(buckets):
        rows = ordered[index * len(ordered) // buckets:(index + 1) * len(ordered) // buckets]
        values = sorted(r[1] for r in rows)
        result.append(dict(bucket=index, size_min_bytes=rows[0][0],
                           size_max_bytes=rows[-1][0], samples=len(rows),
                           input_identity_sha256=input_hash,
                           p99_us=float(values[min(int(len(values) * .99), len(values)-1)])))
    return result


def normalize(rows):
    """Require complete matched repeats; compute ratios BEFORE averaging runs."""
    indexed = {}
    for row in rows:
        key = (row['group'], row['algorithm'], row['repeat'], row['bucket'])
        if not isinstance(row['bucket'], int) or not 0 <= row['bucket'] < BUCKETS:
            raise ValueError(f'Invalid Figure 2 bucket: {key}')
        if key in indexed:
            raise ValueError(f'Duplicate Figure 2 row: {key}')
        if row['group'] not in ('lossless', 'lossy') or row['algorithm'] not in ALGORITHMS:
            raise ValueError(f'Unexpected Figure 2 condition: {key}')
        if not math.isfinite(row['p99_us']) or row['p99_us'] <= 0 or row['samples'] < 1:
            raise ValueError(f'Invalid P99/sample count: {key}')
        indexed[key] = row
    if not indexed:
        raise ValueError('No Figure 2 size-bucket data; run parse on completed experiments first')
    curves = []
    for fabric in sorted({key[0] for key in indexed}):
        repeats = sorted({key[2] for key in indexed if key[0] == fabric})
        for algorithm in ALGORITHMS:
            for bucket in range(BUCKETS):
                ratios, sizes, counts = [], [], []
                for repeat in repeats:
                    key = (fabric, algorithm, repeat, bucket)
                    baseline_key = (fabric, 'BigSwitch', repeat, bucket)
                    if key not in indexed or baseline_key not in indexed:
                        raise ValueError(f'Incomplete Figure 2 comparison: missing {key} or {baseline_key}')
                    row, baseline = indexed[key], indexed[baseline_key]
                    for field in ('size_min_bytes', 'size_max_bytes', 'samples', 'input_identity_sha256'):
                        if row[field] != baseline[field]:
                            raise ValueError(f'Unmatched input/bucket {field}: {key}')
                    ratios.append(row['p99_us'] / baseline['p99_us'])
                    sizes.append(baseline['size_max_bytes'])
                    counts.append(row['samples'])
                curves.append(dict(group=fabric, algorithm=algorithm, bucket=bucket,
                                   size_max_bytes=float(np.mean(sizes)),
                                   normalized_p99=float(np.mean(ratios)),
                                   repeat_min=float(min(ratios)), repeat_max=float(max(ratios)),
                                   repeats=len(repeats), samples=sum(counts)))
    return curves
