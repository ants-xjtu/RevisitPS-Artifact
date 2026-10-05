"""Executed inside SDE after configuration: bind program and read physical ports."""
import argparse
import hashlib
import json
import time
from framework.conf_parser.yaml_parser import SwitchConfParser
from switches.bfrt.bfrt_grpc_client import BfrtGrpcClient, gc
from switches.bfrt.port_controller import PortController


def verify(args):
    conf = SwitchConfParser(args.switches)
    conf.load_conf_file()
    switch = conf.switches[args.hostname]
    client = BfrtGrpcClient(switch['program']['name'], args.hostname, args.switches, None, None)
    client.setup(switch['program']['name'], '127.0.0.1', args.bfrt_port, client_id=97)
    ports = PortController(client.target, gc, client.bfrt_info)
    table = client.bfrt_info.table_get('$PORT')
    expected = bool(switch.get('PFC_ENABLE', False))
    readback = {'program': switch['program']['name'], 'ports': [], 'tables': {}}
    for fp, lane, *_ in conf.parse_ports(args.hostname):
        ok, dev_port = ports.get_dev_port(fp, lane)
        if not ok:
            raise RuntimeError(f'Unknown physical port {fp}/{lane}')
        deadline = time.monotonic() + 60
        while True:
            data, _ = next(table.entry_get(client.target, [table.make_key([gc.KeyTuple('$DEV_PORT', dev_port)])], {'from_hw': True}))
            values = data.to_dict()
            if values.get('$PORT_ENABLE') and values.get('$PORT_UP'):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Physical port {fp}/{lane} is not UP: {values}')
            time.sleep(1)
        for name in ('$TX_PFC_EN_MAP', '$RX_PFC_EN_MAP'):
            if values.get(name) != (255 if expected else 0):
                raise RuntimeError(f'Port {fp}/{lane}: {name} readback mismatch')
        readback['ports'].append([dev_port, {name: values.get(name) for name in (
            '$PORT_ENABLE', '$PORT_UP', '$SPEED', '$FEC', '$TX_PFC_EN_MAP', '$RX_PFC_EN_MAP')}])
    program = switch['program']['name']
    table_names = ['pipe.SwitchIngress.forward'] if program.startswith('basic_forward') else [
        'pipe.SwitchIngress.get_nexthop_id', 'pipe.SwitchIngress.nexthop',
        'pipe.SwitchIngress.lag_ecmp', 'pipe.SwitchIngress.lag_ecmp_sel']
    for name in table_names:
        table = client.bfrt_info.table_get(name)
        entries = list(table.entry_get(client.target, [], {'from_hw': True}))
        if not entries:
            raise RuntimeError(f'Forwarding table {name} is empty')
        rows = [(data.to_dict(), key.to_dict()) for data, key in entries]
        readback['tables'][name] = sorted(json.dumps(row, sort_keys=True) for row in rows)
        print(name, rows)
    readback['ports'].sort(key=lambda row: row[0])
    checksum = hashlib.sha256(json.dumps(readback, sort_keys=True).encode()).hexdigest()
    print('ARTIFACT_SWITCH_STATE=' + checksum)
    print('Verified program binding, forwarding entries, physical ports and PFC readback')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--switches', required=True)
    parser.add_argument('--bfrt-port', type=int, required=True)
    verify(parser.parse_args())
