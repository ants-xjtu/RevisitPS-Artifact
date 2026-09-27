"""Sync deterministic traces to every actual sending host and verify checksums."""
import hashlib
from pathlib import Path
import shlex
import click
from conf_parser.yaml_parser import HostConfParser, ConnectionConfParser
from common.remote_rdma_helper import generate_ip_helper_map


def validate_trace(path):
    lines = Path(path).read_text().splitlines()
    count = int(lines[0])
    rows = [tuple(map(int, line.split())) for line in lines[1:]]
    if count <= 0 or count != len(rows):
        raise ValueError(f'{path}: empty/mismatched trace count (fork requires a nonempty trace)')
    previous = -1
    for size, timestamp in rows:
        if size <= 0 or timestamp < previous:
            raise ValueError(f'{path}: invalid size or time order')
        previous = timestamp
    return [size for size, _ in rows]


@click.command()
def sync_trace(test_conf_parser):
    conf = test_conf_parser.get()
    hosts = HostConfParser(conf.config.hosts)
    hosts.load_conf_file()
    links = ConnectionConfParser(conf.config.connections)
    links.load_conf_file()
    helpers = generate_ip_helper_map({c['sender'] for c in links.connections}, hosts.hosts, conf.applications.remote_rdma.user)
    source = Path(conf.applications.gen_trace.local_path)
    hashes = {}
    for connection in links.connections:
        name = f"{connection['sender']}-{connection['receiver']}.trace"
        validate_trace(source / name)
        hashes[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
    seen = set()
    for helper in helpers.values():
        if helper.target in seen:
            continue
        seen.add(helper.target)
        destination = helper.absolute(conf.applications.gen_trace.remote_path)
        helper.sync_local_to_remote(source, destination)
        for name, digest in hashes.items():
            actual = helper.ssh('sha256sum ' + shlex.quote(destination + '/' + name)).stdout.split()[0]
            if actual != digest:
                raise RuntimeError(f'{helper.target}: trace checksum mismatch: {name}')
