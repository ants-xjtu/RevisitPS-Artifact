"""Read selected NICs in one SSH session per management host."""
import json
import re
import shlex
from pathlib import Path

from framework.progress import progress
from framework.remote import find_roce_v2_gid, SSHConnectionError


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


def discover(hosts, helpers, cache=None):
    for group in host_groups(helpers):
        remote = next(iter(group.values()))
        key = tuple(sorted((ip, helper.target, helper.interface,
                            hosts.hosts[ip].get('mlx_device_name'), hosts.hosts[ip].get('bus_info'))
                           for ip, helper in group.items()))
        saved = cache.get(key) if cache is not None else None
        if saved:
            # Recheck boot, device/PCI mapping and the selected GID; avoid enumerating
            # every GID slot and invoking ethtool again for stable device metadata.
            queries = {'boot': 'cat /proc/sys/kernel/random/boot_id'}
            for ip, helper in group.items():
                info = saved['devices'][ip]
                net = '/sys/class/net/' + helper.interface + '/device'
                device = net + '/infiniband/' + info['mlx_device_name']
                port = device + '/ports/1'
                index = str(info['gid'])
                queries[ip + '/device'] = 'test -d ' + shlex.quote(device) + ' && printf %s ' + shlex.quote(info['mlx_device_name'])
                queries[ip + '/bus'] = 'basename "$(readlink -f ' + shlex.quote(net) + ')"'
                queries[ip + '/gid'] = ('printf "%s %s %s\\n" ' + index + ' "$(cat ' +
                    shlex.quote(port + '/gids/' + index) + ')" "$(cat ' +
                    shlex.quote(port + '/gid_attrs/types/' + index) + ')"')
            try:
                actual = {name: value.strip() for name, value in read_batch(remote, queries).items()}
            except SSHConnectionError:
                raise
            except (RuntimeError, ValueError):
                actual = None
            if actual == saved['identity']:
                for ip, helper in group.items():
                    for name, value in saved['devices'][ip].items():
                        setattr(helper, name, value)
                    helper.boot_id = actual['boot']
                    hosts.add_host_info(ip, saved['devices'][ip])
                progress(f'NIC discovery reused after identity/GID checks: {remote.target}')
                continue
            cache.pop(key, None)
        progress(f'NIC discovery: {remote.target}, {len(group)} ports')
        commands = {'mapping': 'for dev in /sys/class/infiniband/mlx*; do '
                    'for net in "$dev"/device/net/*; do '
                    'printf "%s %s\\n" "${dev##*/}" "${net##*/}"; done; done'}
        if cache is not None:
            commands['boot'] = 'cat /proc/sys/kernel/random/boot_id'
        for ip, helper in group.items():
            commands[ip + '/driver'] = 'ethtool -i ' + shlex.quote(helper.interface)
            prefix = shlex.quote('/sys/class/net/' + helper.interface + '/device/infiniband')
            commands[ip + '/gids'] = (f'for dev in {prefix}/*; do '
                'for f in "$dev"/ports/1/gids/*; do '
                'printf "%s %s %s %s\\n" "${dev##*/}" "${f##*/}" "$(cat "$f")" '
                '"$(cat "$dev"/ports/1/gid_attrs/types/"${f##*/}")"; done; done')
        snapshot = read_batch(remote, commands)
        mapping = [line.split() for line in snapshot['mapping'].splitlines()]
        devices = {}
        identity = {'boot': snapshot.get('boot', '').strip()}
        for ip, helper in group.items():
            helper.mlx_device_name = next((dev for dev, iface in mapping if iface == helper.interface), None)
            driver = re.search(r'bus-info:\s*(\S+)', snapshot[ip + '/driver'])
            if not helper.mlx_device_name or not driver:
                raise RuntimeError(f'{ip}: missing verbs mapping or PCI bus address')
            helper.bus_info = driver[1]
            for field in ('mlx_device_name', 'bus_info'):
                if hosts.hosts[ip].get(field) and hosts.hosts[ip][field] != getattr(helper, field):
                    raise RuntimeError(f'{ip}: configured {field} differs from device probe')
            # Remove only the batch transport's device prefix, then reuse the
            # existing index/address/type parser, including its empty-slot guard.
            gid_lines = []
            for line in snapshot[ip + '/gids'].splitlines():
                fields = line.split(maxsplit=1)
                if len(fields) == 2 and fields[0] == helper.mlx_device_name:
                    gid_lines.append(fields[1])
            helper.gid = find_roce_v2_gid('\n'.join(gid_lines), ip)
            helper.boot_id = identity['boot']
            devices[ip] = {name: getattr(helper, name) for name in ('mlx_device_name', 'bus_info', 'gid')}
            identity.update({ip + '/device': helper.mlx_device_name, ip + '/bus': helper.bus_info,
                             ip + '/gid': next(line.strip() for line in gid_lines if line.split()[0] == str(helper.gid))})
            hosts.add_host_info(ip, devices[ip])
        if cache is not None:
            cache[key] = dict(devices=devices, identity=identity)
