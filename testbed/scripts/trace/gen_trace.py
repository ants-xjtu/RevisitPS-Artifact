"""Deterministic Poisson trace generation: load per host or per connection."""
import heapq
import math
from pathlib import Path
import random
import click
from .custom_rand import CustomRand
from conf_parser.yaml_parser import ConnectionConfParser


def translate_bandwidth(value):
    factors = {'G': 1e9, 'M': 1e6, 'K': 1e3}
    return float(value[:-1]) * factors[value[-1]] if value[-1] in factors else float(value)


def generate(parser, mode):
    conf = parser.get()
    settings = conf.applications.gen_trace
    random.seed(settings.get('seed', 42))
    bandwidth, load, seconds = translate_bandwidth(settings.bandwidth), float(settings.load), float(settings.time)
    if bandwidth <= 0 or not 0 < load <= 1 or seconds <= 0:
        raise ValueError('Trace bandwidth/time must be positive and load must be in (0,1]')
    cdf = [list(map(float, line.split())) for line in Path(settings.cdf).read_text().splitlines() if line.strip()]
    distribution = CustomRand()
    if not distribution.setCdf(cdf):
        raise ValueError('Invalid CDF')
    links = ConnectionConfParser(conf.config.connections)
    links.load_conf_file()
    pairs = sorted({(c['sender'], c['receiver']) for c in links.connections})
    destinations = {}
    for src, dst in pairs:
        destinations.setdefault(src, []).append(dst)
    streams = sorted(destinations) if mode == 'host' else pairs
    if not streams:
        raise ValueError('Empty connection set')
    mean_gap = distribution.getAvg() * 8 / (bandwidth * load) * 1e9
    def gap():
        return max(1, int(-math.log1p(-random.random()) * mean_gap))
    base, end = 2_000_000_000, 2_000_000_000 + int(seconds * 1e9)
    events = [(base + gap(), stream) for stream in streams]
    heapq.heapify(events)
    rows = {pair: [] for pair in pairs}
    while events:
        timestamp, stream = heapq.heappop(events)
        if timestamp > end:
            continue
        pair = (stream, random.choice(destinations[stream])) if mode == 'host' else stream
        rows[pair].append((max(1, int(distribution.rand())), timestamp))
        heapq.heappush(events, (timestamp + gap(), stream))
    output = Path(settings.local_path)
    output.mkdir(parents=True, exist_ok=True)
    for (src, dst), values in rows.items():
        if not values:
            raise ValueError(f'{src}->{dst}: trace is empty; pinned fork cannot execute zero-flow inputs')
        (output / f'{src}-{dst}.trace').write_text(str(len(values)) + '\n' + ''.join(f'{size} {t}\n' for size, t in values))


@click.command()
def gen_trace_from_host(test_conf_parser):
    generate(test_conf_parser, 'host')


@click.command()
def gen_trace_from_connection(test_conf_parser):
    generate(test_conf_parser, 'connection')
