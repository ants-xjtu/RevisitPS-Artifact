"""Atomic result state, streaming checksums and completion integrity checks."""
import csv
import hashlib
import json
import os
from pathlib import Path
import yaml


def yaml_read(path):
    return yaml.safe_load(Path(path).read_text())

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def intact(task, run_dir):
    attempt = run_dir / task['attempt']
    if not task.get('files') or not all((attempt / p).is_file() and digest(attempt / p) == checksum for p, checksum in task['files'].items()):
        return False
    if task.get('trace_hashes'):
        runtime = yaml_read(attempt / 'configs/runtime.yaml')
        trace_dir = Path(runtime['applications']['gen_trace']['local_path'])
        return all((trace_dir / name).is_file() and digest(trace_dir / name) == checksum for name, checksum in task['trace_hashes'].items())
    return True


def manifest(run_dir, status):
    target = run_dir / 'manifest.csv'
    tmp = target.with_suffix('.tmp')
    fields = ['task_id', 'experiment', 'repeat', 'status', 'input_hash', 'attempt', 'started', 'finished', 'exit_code', 'error']
    with tmp.open('w') as output:
        writer = csv.DictWriter(output, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(status['tasks'].values())
    tmp.replace(target)


def persist(run_dir, status):
    atomic_json(run_dir / 'status.json', status)
    manifest(run_dir, status)


