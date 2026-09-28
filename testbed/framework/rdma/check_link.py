"""Sequential, directional line-rate acceptance using the pinned fork's interval BW."""
import json
from pathlib import Path
import click
from framework.rdma.run_test import load_endpoints, execute_connections
from experiments.dcn_workload.scripts.plot_throughput import read_intervals, window_average


def check_links(parser, connections=None):
    requested = {link[end] for link in (connections or []) for end in ('sender', 'receiver')}
    _, configured, helpers = load_endpoints(parser, requested)
    conf = parser.get().applications.remote_rdma.check
    measurement = parser.get().artifact.measurement
    pairs = connections if connections is not None else configured
    directions = {(c['sender'], c['receiver']) for c in pairs}
    if measurement.bidirectional:
        directions |= {(dst, src) for src, dst in list(directions)}
    report = []
    root = Path(conf.local_log)
    root.mkdir(parents=True, exist_ok=True)
    try:
        for src, dst in sorted(directions):
            pair_dir = root / f'{src}-{dst}'
            pair_dir.mkdir(exist_ok=True)
            conf.local_log = str(pair_dir)
            for ip in (src, dst):
                (pair_dir / f'{ip}.counters.before').write_text(helpers[ip].get_counter())
            row = dict(src=src, dst=dst, direction=f'{src}->{dst}',
                       duration=measurement.duration_seconds, average_gbps=None,
                       threshold_gbps=measurement.threshold_gbps, exit_code=None,
                       passed=False, log_path=str(pair_dir))
            report.append(row)
            try:
                execute_connections(parser, [{'sender': src, 'receiver': dst}], helpers,
                                    section='check', duration=measurement.warmup_seconds + measurement.duration_seconds + 2)
                rows = read_intervals(pair_dir / f'{src}-{dst}.sender.log')
                avg = window_average(rows, measurement.warmup_seconds,
                                     measurement.warmup_seconds + measurement.duration_seconds)
                row.update(average_gbps=avg, exit_code=0, passed=avg >= measurement.threshold_gbps)
                if not row['passed']:
                    raise RuntimeError(f'{src}->{dst}: {avg:.3f} Gbps < {measurement.threshold_gbps} Gbps')
            except Exception as exc:
                row['error'] = str(exc)
                raise
            finally:
                (root / 'report.json').write_text(json.dumps(report, indent=2))
    finally:
        conf.local_log = str(root)
    return report


@click.command()
@click.option('--src', required=True)
@click.option('--dst', required=True)
def check_one_link(test_conf_parser, src, dst):
    return check_links(test_conf_parser, [{'sender': src, 'receiver': dst}])


@click.command()
def check_all_links(test_conf_parser):
    return check_links(test_conf_parser)


def verify_trace_support(parser, connections, helpers, folder):
    """Short on-hardware format check in the check stage, once per sending host.

    Formal run/all stages do not send this diagnostic traffic.
    """
    import copy
    from framework.conf_parser.yaml_parser import yaml_to_dataclass
    from experiments.dcn_workload.scripts.parse import parse_fct
    original = parser.get().applications.remote_rdma.test
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    seen = set()
    try:
        for connection in connections:
            src, dst = connection['sender'], connection['receiver']
            if helpers[src].target in seen:
                continue
            seen.add(helpers[src].target)
            stem = f'{src}-{dst}'
            local = folder / stem
            local.mkdir(exist_ok=True)
            trace_dir = local / 'trace'
            trace_dir.mkdir(exist_ok=True)
            trace_name = stem + '.trace'
            (trace_dir / trace_name).write_text('3\n4096 2000000000\n8192 2100000000\n16384 2200000000\n')
            remote_dir = original.remote_log + '/smoke-' + stem
            helpers[src].sync_local_to_remote(trace_dir, remote_dir + '/trace')
            command = ('stdbuf -oL -eL {{binary_dir}}/ib_write_trace -d {{mlx_device_name}} '
                       '-i 1 -x {{gid}} --report_gbits -p {{port}} -s 65536 '
                       '--disable_pcie_relaxed -m 1024 -F -q 1 -t 128 -Q 1 --qp-timeout=14')
            parser.get().applications.remote_rdma.test = yaml_to_dataclass('Smoke', {
                'local_log': str(local), 'remote_log': remote_dir, 'remote_trace_dir': remote_dir + '/trace',
                'cmd': {'base_port': original.cmd.base_port, 'timeout': 30, 'config': {},
                        'receiver': command, 'sender': command + ' {{receiver_ip}} --trace {{trace}}'}})
            execute_connections(parser, [connection], {ip: helpers[ip] for ip in (src, dst)})
            records, counts = parse_fct(local / (stem + '.sender.log.csv'), [4096, 8192, 16384])
            if counts['valid'] != 3 or any(counts[k] for k in ('incomplete', 'nonpositive', 'malformed')):
                raise RuntimeError('Pinned fork trace smoke/format check failed: ' + str(counts))
            # Trace schedule gaps are ns; report gaps must be about 100,000 us.
            gaps = [records[i+1]['start_time_us'] - records[i]['start_time_us'] for i in range(2)]
            if not all(50_000 < gap < 1_000_000 for gap in gaps):
                raise RuntimeError('Trace timestamp unit check failed: ' + str(gaps))
    finally:
        parser.get().applications.remote_rdma.test = original
