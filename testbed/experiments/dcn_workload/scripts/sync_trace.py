"""Sync deterministic traces to every actual sending host and verify checksums."""
import hashlib
from pathlib import Path
import shlex
import click
from framework.conf_parser.yaml_parser import HostConfParser, ConnectionConfParser
from framework.remote import generate_ip_helper_map


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
def sync_trace(test_conf_parser, hashes=None):
    conf = test_conf_parser.get()
    hosts = HostConfParser(conf.config.hosts)
    hosts.load_conf_file()
    links = ConnectionConfParser(conf.config.connections)
    links.load_conf_file()
    helpers = generate_ip_helper_map({c['sender'] for c in links.connections}, hosts.hosts, conf.applications.remote_rdma.user)
    source = Path(conf.applications.gen_trace.local_path)
    names = [f"{connection['sender']}-{connection['receiver']}.trace" for connection in links.connections]
    if hashes is None:
        hashes = {}
        for name in names:
            validate_trace(source / name)
            hashes[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
    if set(hashes) != set(names):
        raise ValueError('Trace checksum manifest does not match connections')
    manifest = ''.join(f'{hashes[name]}  {name}\n' for name in names)
    seen = set()
    for helper in helpers.values():
        if helper.target in seen:
            continue
        seen.add(helper.target)
        destination = helper.absolute(conf.applications.gen_trace.remote_path)
        helper.sync_local_to_remote(source, destination)
        helper.ssh('cd ' + shlex.quote(destination) + ' && printf %s ' +
                   shlex.quote(manifest) + ' | sha256sum -c -')
