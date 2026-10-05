"""Configure selected endpoints only, then read effective values back."""
import argparse
import json
from pathlib import Path
import re
import shlex
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from framework.conf_parser.yaml_parser import HostConfParser
from framework.remote import generate_ip_helper_map
from framework.rdma.nic_batch import discover, host_groups, read_batch
from framework.progress import progress


def probe_port(helper, rdma, require_up=True):
    iface = shlex.quote(helper.interface)
    link = helper.ssh(f'ip -j address show dev {iface}').stdout
    speed = helper.ssh('ethtool ' + iface).stdout
    return validate_port(helper, rdma, link, speed, require_up)


def validate_port(helper, rdma, link, speed, require_up=True):
    ip = helper.ip
    device = json.loads(link)[0]
    if (require_up and device['operstate'] != 'UP') or device['mtu'] < rdma['mtu']:
        raise RuntimeError(f'{ip}: link down or insufficient MTU')
    if ip not in [addr['local'] for addr in device['addr_info']]:
        raise RuntimeError(f'{ip}: configured address is not on {helper.interface}')
    match = re.search(r'Speed:\s*(\d+)Mb/s', speed)
    if require_up and (not match or int(match[1]) < rdma['min_speed_mbps'] or 'Link detected: yes' not in speed):
        raise RuntimeError(f'{ip}: physical link is not 100G')
    return device


def verify_psn_window(helper, packets):
    """Check CURRENT firmware state; Next Boot alone is not evidence."""
    output = helper.ssh('sudo -n mlxconfig -d ' + shlex.quote(helper.bus_info) +
                        ' -e query LOG_TX_PSN_WINDOW').stdout
    validate_psn_window(helper, packets, output)


def validate_psn_window(helper, packets, output):
    if packets < 1 or packets & (packets - 1):
        raise ValueError('PSN window must be a positive power of two')
    if not re.search(r'Default\s+Current\s+Next Boot', output):
        raise RuntimeError(f'{helper.ip}: mlxconfig did not report the current PSN window')
    match = re.search(r'^\s*LOG_TX_PSN_WINDOW\s+\S+\s+(0x[0-9a-fA-F]+|[0-9]+)\s+\S+', output, re.MULTILINE)
    value = int(match[1], 16 if match[1].startswith('0x') else 10) if match else None
    if value != packets.bit_length() - 1:
        raise RuntimeError(f'{helper.ip}: current LOG_TX_PSN_WINDOW must be {packets.bit_length()-1} '
                           f'({packets} packets); provision firmware configuration before running')


# Runtime sysfs controls used by the existing DCQCN enable setter. Keep the
# parameter names explicit so configuration cannot address arbitrary files.
DCQCN_PARAMETERS = {
    'roce_rp': frozenset(('clamp_tgt_rate', 'clamp_tgt_rate_after_time_inc',
        'dce_tcp_g', 'dce_tcp_rtt', 'initial_alpha_value',
        'rate_reduce_monitor_period', 'rate_to_set_on_first_cnp',
        'rpg_ai_rate', 'rpg_byte_reset', 'rpg_gd', 'rpg_hai_rate',
        'rpg_max_rate', 'rpg_min_dec_fac', 'rpg_min_rate',
        'rpg_threshold', 'rpg_time_reset')),
    'roce_np': frozenset(('cnp_802p_prio', 'cnp_dscp', 'min_time_between_cnps')),
}


def dcqcn_values(rdma, ip):
    enabled = rdma.get('dcqcn_overrides', {}).get(ip, rdma['dcqcn'])
    if enabled not in (0, 1):
        raise ValueError(f'{ip}: DCQCN must be 0 or 1')
    values = {direction + '/enable/0': int(enabled) for direction in DCQCN_PARAMETERS}
    parameters = rdma.get('dcqcn_parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('dcqcn_parameters must be a mapping')
    for direction, settings in parameters.items():
        if direction not in DCQCN_PARAMETERS or not isinstance(settings, dict):
            raise ValueError(f'Invalid DCQCN parameter group: {direction}')
        for name, value in settings.items():
            if name not in DCQCN_PARAMETERS[direction] or type(value) is not int or value < 0:
                raise ValueError(f'Invalid DCQCN parameter: {direction}/{name}={value!r}')
            values[direction + '/' + name] = value
    return values


def dcqcn_queries(group, rdma):
    return {ip + '/dcqcn/' + name:
            'cat ' + shlex.quote(f'/sys/class/net/{helper.interface}/ecn/{name}')
            for ip, helper in group.items() for name in dcqcn_values(rdma, ip)}


def dcqcn_changes(group, rdma, snapshot):
    changes = []
    for ip, helper in group.items():
        for name, value in dcqcn_values(rdma, ip).items():
            current = snapshot[ip + '/dcqcn/' + name].strip()
            if not re.fullmatch(r'[0-9]+', current):
                raise RuntimeError(f'{ip}: invalid DCQCN {name} readback: {current!r}')
            if name.endswith('/enable/0') and current not in ('0', '1'):
                raise RuntimeError(f'{ip}: invalid DCQCN {name} readback: {current!r}')
            if int(current) != value:
                path = f'/sys/class/net/{helper.interface}/ecn/{name}'
                changes.append(f'printf %s {value} | sudo -n tee {shlex.quote(path)} >/dev/null')
    return changes


def configure_dcqcn(helpers, deployment, apply=True):
    """Prepare host congestion control without changing fabric/PFC settings."""
    rdma = deployment['rdma']
    for group in host_groups(helpers):
        configure_group(group, dcqcn_queries(group, rdma),
                        lambda snapshot: dcqcn_changes(group, rdma, snapshot),
                        apply, label='DCQCN')


def nic_queries(hosts, group, rdma):
    commands = dcqcn_queries(group, rdma)
    for ip, helper in group.items():
        iface, bus = shlex.quote(helper.interface), shlex.quote(helper.bus_info)
        commands[ip + '/link'] = 'ip -j address show dev ' + iface
        commands[ip + '/speed'] = 'ethtool ' + iface
        commands[ip + '/qos'] = 'sudo -n mlnx_qos -i ' + iface
        if 'psn_window_packets' in rdma:
            commands[ip + '/psn'] = 'sudo -n mlxconfig -d ' + bus + ' -e query LOG_TX_PSN_WINDOW'
        for register in hosts.hosts[ip].get('mlxreg', {}):
            commands[ip + '/reg/' + register] = ('sudo -n mlxreg -d ' + bus +
                ' --reg_name ' + shlex.quote(register) + ' --get')
    return commands


def nic_changes(hosts, group, rdma, lossless, snapshot):
    changes = dcqcn_changes(group, rdma, snapshot)
    pfc = lossless if rdma['pfc'] == 'auto' else bool(rdma['pfc'])
    expected = [int(pfc), 0, 0, 0, 0, 0, 0, 0]
    for ip, helper in group.items():
        iface = shlex.quote(helper.interface)
        validate_port(helper, rdma, snapshot[ip + '/link'], snapshot[ip + '/speed'])
        if 'psn_window_packets' in rdma:
            validate_psn_window(helper, rdma['psn_window_packets'], snapshot[ip + '/psn'])
        qos = snapshot[ip + '/qos']
        enabled = re.search(r'^\s*enabled\s+([01](?:\s+[01]){7})\s*$', qos, re.IGNORECASE | re.MULTILINE)
        trust = re.search(r'Priority trust state:\s*(\w+)', qos, re.IGNORECASE)
        if not enabled or not trust:
            raise RuntimeError(f'{ip}: cannot parse PFC/trust state; refusing to write unknown state')
        options = []
        if list(map(int, enabled[1].split())) != expected:
            options.append('--pfc ' + ','.join(map(str, expected)))
        if trust[1].lower() != 'dscp':
            options.append('--trust=dscp')
        if options:
            changes.append(f'sudo -n mlnx_qos -i {iface} ' + ' '.join(options))
        for register, values in hosts.hosts[ip].get('mlxreg', {}).items():
            output = snapshot[ip + '/reg/' + register]
            different = {}
            for key, value in values.items():
                match = re.search(r'^\s*' + re.escape(key) + r'\s+\|?\s*(0x[0-9a-fA-F]+|[0-9]+)\b',
                                  output, re.MULTILINE)
                if not match:
                    raise RuntimeError(f'{ip}: cannot read {register}.{key}; refusing to write unknown state')
                current = int(match[1], 16 if match[1].startswith('0x') else 10)
                if current != int(value):
                    different[key] = int(value)
            if different:
                options = ','.join(f'{key}={value}' for key, value in different.items())
                changes.append('sudo -n mlxreg -d ' + shlex.quote(helper.bus_info) +
                    ' --reg_name ' + shlex.quote(register) + ' -y --set ' + shlex.quote(options))
    return changes


def configure_group(group, queries, changes_for, apply, label='NIC'):
    remote = next(iter(group.values()))
    progress(f'{label} state: {remote.target}, reading {len(group)} ports in one SSH session')
    current = read_batch(remote, queries)
    changes = changes_for(current)
    if not changes:
        progress(f'{label} ready: {remote.target}, all {len(group)} ports match; no writes')
        return current
    if not apply:
        raise RuntimeError(f'{remote.target}: {label} configuration mismatch; {len(changes)} updates required')
    progress(f'{label} update: {remote.target}, applying {len(changes)} changed settings groups')
    remote.ssh('\n'.join(changes), timeout=max(60, 10 * len(changes)))
    actual = read_batch(remote, queries)
    remaining = changes_for(actual)
    if remaining:
        raise RuntimeError(f'{remote.target}: {label} readback mismatch after update: ' + '; '.join(remaining))
    progress(f'{label} ready: {remote.target}, all {len(group)} ports verified after update')
    return actual


def configure(hosts, helpers, deployment, lossless, apply=True, firmware_cache=None):
    rdma = deployment['rdma']
    for group in host_groups(helpers):
        queries = nic_queries(hosts, group, rdma)
        # LOG_TX_PSN_WINDOW is a boot-time firmware setting. Other NIC settings
        # (link, QoS, DCQCN and runtime registers) are always read back live.
        key = tuple(sorted((ip, h.target, h.bus_info, getattr(h, 'boot_id', ''),
                            rdma.get('psn_window_packets')) for ip, h in group.items()))
        can_cache = firmware_cache is not None and all(getattr(h, 'boot_id', '') for h in group.values())
        saved = firmware_cache.get(key, {}) if can_cache else {}
        for name in saved:
            queries.pop(name, None)
        actual = configure_group(group, queries,
            lambda snapshot: nic_changes(hosts, group, rdma, lossless, {**saved, **snapshot}), apply)
        if can_cache:
            firmware_cache[key] = {name: value for name, value in {**saved, **actual}.items()
                                   if name.endswith('/psn')}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--hosts', required=True)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--lossless', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--dcqcn', type=int, choices=[0, 1])
    args = parser.parse_args(argv)
    config = yaml.safe_load(Path(args.deployment).read_text())
    if args.dcqcn is not None:
        config['rdma']['dcqcn'] = bool(args.dcqcn)
    hosts = HostConfParser(args.hosts)
    hosts.load_conf_file()
    helpers = generate_ip_helper_map(hosts.hosts, hosts.hosts, config['rdma']['user'])
    discover(hosts, helpers)
    configure(hosts, helpers, config, args.lossless, not args.check)


if __name__ == '__main__':
    main()
