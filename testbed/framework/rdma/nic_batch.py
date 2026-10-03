"""Read selected NICs in one SSH session per management host."""
import json
import re
import shlex
from pathlib import Path

from framework.progress import progress
from framework.remote import find_roce_v2_gid


_QUERY_SCRIPT = '''import json, subprocess, sys
outputs = {}
for key, command in json.loads(sys.argv[1]).items():
    result = subprocess.run(['bash', '-c', 'set -euo pipefail; ' + command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    if result.returncode:
        sys.stderr.write('%s: %s\\n%s' % (key, command, result.stderr))
        sys.exit(1)
    outputs[key] = result.stdout
print(json.dumps(outputs))
'''


def host_groups(helpers):
    groups = {}
    for ip, helper in helpers.items():
        groups.setdefault(helper.target, {})[ip] = helper
    return groups.values()


def read_batch(helper, commands):
    """All commands are read-only; a failed query invalidates the whole snapshot."""
    command = 'python3 -c ' + shlex.quote(_QUERY_SCRIPT) + ' ' + shlex.quote(json.dumps(commands))
    return json.loads(helper.ssh(command, timeout=max(60, 10 * len(commands))).stdout)


def collect_counters(helpers, directory, suffix, on_error=None):
    """Read all NIC counters on a host together, preserving per-IP artifacts."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for group in host_groups(helpers):
        remote = next(iter(group.values()))
        try:
            snapshot = read_batch(remote, {ip: helper.counter_command() for ip, helper in group.items()})
            if set(snapshot) != set(group):
                raise RuntimeError(f'{remote.target}: incomplete counter snapshot')
            for ip, output in snapshot.items():
                (directory / (ip + suffix)).write_text(output)
        except Exception as exc:
            if on_error is None:
                raise
            on_error(exc)


def discover(hosts, helpers):
    for group in host_groups(helpers):
        remote = next(iter(group.values()))
        progress(f'NIC discovery: {remote.target}, {len(group)} ports')
        commands = {'mapping': 'for dev in /sys/class/infiniband/mlx*; do '
                    'for net in "$dev"/device/net/*; do '
                    'printf "%s %s\\n" "${dev##*/}" "${net##*/}"; done; done'}
        for ip, helper in group.items():
            commands[ip + '/driver'] = 'ethtool -i ' + shlex.quote(helper.interface)
            prefix = shlex.quote('/sys/class/net/' + helper.interface + '/device/infiniband')
            commands[ip + '/gids'] = (f'for dev in {prefix}/*; do '
                'for f in "$dev"/ports/1/gids/*; do '
                'printf "%s %s %s %s\\n" "${dev##*/}" "${f##*/}" "$(cat "$f")" '
                '"$(cat "$dev"/ports/1/gid_attrs/types/"${f##*/}")"; done; done')
        snapshot = read_batch(remote, commands)
        mapping = [line.split() for line in snapshot['mapping'].splitlines()]
        for ip, helper in group.items():
            helper.mlx_device_name = next((dev for dev, iface in mapping if iface == helper.interface), None)
            driver = re.search(r'bus-info:\s*(\S+)', snapshot[ip + '/driver'])
            if not helper.mlx_device_name or not driver:
                raise RuntimeError(f'{ip}: missing verbs mapping or PCI bus address')
            helper.bus_info = driver[1]
            for key in ('mlx_device_name', 'bus_info'):
                if hosts.hosts[ip].get(key) and hosts.hosts[ip][key] != getattr(helper, key):
                    raise RuntimeError(f'{ip}: configured {key} differs from device probe')
            # Remove only the batch transport's device prefix, then reuse the
            # existing index/address/type parser, including its empty-slot guard.
            gid_lines = []
            for line in snapshot[ip + '/gids'].splitlines():
                fields = line.split(maxsplit=1)
                if len(fields) == 2 and fields[0] == helper.mlx_device_name:
                    gid_lines.append(fields[1])
            helper.gid = find_roce_v2_gid('\n'.join(gid_lines), ip)
            hosts.add_host_info(ip, {key: getattr(helper, key) for key in ('mlx_device_name', 'bus_info', 'gid')})
