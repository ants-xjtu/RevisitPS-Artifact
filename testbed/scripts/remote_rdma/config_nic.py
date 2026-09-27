"""Configure selected endpoints only, then read effective values back."""
import argparse
from pathlib import Path
import re
import shlex
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'utils'))
from conf_parser.yaml_parser import HostConfParser
from common.remote_rdma_helper import generate_ip_helper_map


def probe_port(helper, rdma, require_up=True):
    ip = helper.ip
    iface = shlex.quote(helper.interface)
    link = helper.ssh(f'ip -j address show dev {iface}').stdout
    import json
    device = json.loads(link)[0]
    if (require_up and device['operstate'] != 'UP') or device['mtu'] < rdma['mtu']:
        raise RuntimeError(f'{ip}: link down or insufficient MTU')
    if ip not in [addr['local'] for addr in device['addr_info']]:
        raise RuntimeError(f'{ip}: configured address is not on {helper.interface}')
    speed = helper.ssh('ethtool ' + iface).stdout
    match = re.search(r'Speed:\s*(\d+)Mb/s', speed)
    if require_up and (not match or int(match[1]) < rdma['min_speed_mbps'] or 'Link detected: yes' not in speed):
        raise RuntimeError(f'{ip}: physical link is not 100G')
    return device


def verify_psn_window(helper, packets):
    """Check CURRENT firmware state; Next Boot alone is not evidence."""
    if packets < 1 or packets & (packets - 1):
        raise ValueError('PSN window must be a positive power of two')
    output = helper.ssh('sudo -n mlxconfig -d ' + shlex.quote(helper.bus_info) +
                        ' -e query LOG_TX_PSN_WINDOW').stdout
    if not re.search(r'Default\s+Current\s+Next Boot', output):
        raise RuntimeError(f'{helper.ip}: mlxconfig did not report the current PSN window')
    match = re.search(r'^\s*LOG_TX_PSN_WINDOW\s+\S+\s+(0x[0-9a-fA-F]+|[0-9]+)\s+\S+', output, re.MULTILINE)
    value = int(match[1], 16 if match[1].startswith('0x') else 10) if match else None
    if value != packets.bit_length() - 1:
        raise RuntimeError(f'{helper.ip}: current LOG_TX_PSN_WINDOW must be {packets.bit_length()-1} '
                           f'({packets} packets); provision firmware configuration before running')


def configure(hosts, helpers, deployment, lossless, apply=True):
    rdma = deployment['rdma']
    for ip, helper in helpers.items():
        q = shlex.quote
        iface = q(helper.interface)
        probe_port(helper, rdma)
        if 'psn_window_packets' in rdma:
            verify_psn_window(helper, rdma['psn_window_packets'])
        pfc = lossless if rdma['pfc'] == 'auto' else bool(rdma['pfc'])
        expected = [int(pfc), 0, 0, 0, 0, 0, 0, 0]
        if apply:
            helper.ssh(f'sudo -n mlnx_qos -i {iface} --pfc ' + ','.join(map(str, expected)) + ' --trust=dscp')
        readback = helper.ssh(f'sudo -n mlnx_qos -i {iface}').stdout
        enabled = re.search(r'enabled\s+([01](?:\s+[01]){7})', readback, re.IGNORECASE)
        if not enabled or list(map(int, enabled[1].split())) != expected:
            raise RuntimeError(f'{ip}: PFC effective readback mismatch')
        dcqcn = int(rdma.get('dcqcn_overrides', {}).get(ip, rdma['dcqcn']))
        for direction in ('roce_rp', 'roce_np'):
            path = f'/sys/class/net/{helper.interface}/ecn/{direction}/enable/0'
            if apply:
                helper.ssh(f'printf %s {dcqcn} | sudo -n tee {q(path)} >/dev/null')
            if helper.ssh('cat ' + q(path)).stdout.strip() != str(dcqcn):
                raise RuntimeError(f'{ip}: DCQCN readback failed')
        if apply:
            for register, values in hosts.hosts[ip].get('mlxreg', {}).items():
                helper.config_mlxreg(register, values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hosts', required=True)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--lossless', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--dcqcn', type=int, choices=[0, 1])
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.deployment).read_text())
    if args.dcqcn is not None:
        config['rdma']['dcqcn'] = bool(args.dcqcn)
    hosts = HostConfParser(args.hosts)
    hosts.load_conf_file()
    helpers = generate_ip_helper_map(hosts.hosts, hosts.hosts, config['rdma']['user'])
    for helper in helpers.values():
        helper.get_mellanox_info(hosts)
    configure(hosts, helpers, config, args.lossless, not args.check)


if __name__ == '__main__':
    main()
