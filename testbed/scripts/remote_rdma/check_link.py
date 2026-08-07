import os
from datetime import datetime
import time
import re
import click
from conf_parser.yaml_parser import TestConfParser, HostConfParser, ConnectionConfParser
from common.remote_rdma_helper import RemoteRDMAHelper, generate_ip_helper_map
from common.repo_helper import get_remote_user

@click.group()
def cli():
    """Switch configuration tool with build/run/config commands"""
    pass


# ⭐️ 安全格式化數字/字符串
def fmt_num(val, width=15):
    if isinstance(val, int):
        return f"{val:<{width},}"
    else:
        return f"{str(val):<{width}}"

def analyze_output(output_text, previous_summary=None):
    """
    解析日誌內容，返回計數器字典和報告，可選擇性地與上次數據比較生成差值。
    """
    current_summary = {}
    issues = []
    pattern = re.compile(r'^\s*([\w_]+):\s*(\d+)')

    for line in output_text.splitlines():
        match = pattern.match(line)
        if not match: continue
        key, value = match.groups()
        current_summary[key] = int(value)

    # 檢查錯誤計數器
    for key, value in current_summary.items():
        if any(keyword in key for keyword in ['drop', 'discard', 'error', 'err', 'overrun']):
            # 如果有上次數據，只報告增量問題
            prev_val = previous_summary.get(key, 0) if previous_summary else 0
            if value > prev_val:
                issues.append(f"  - [!!] {key}: {value} (+{value - prev_val})")

    # 格式化報告
    report = "\n    --- Analysis Summary ---\n"
    
    # ⭐️ 如果有上次數據，計算並顯示差值 (Delta)
    if previous_summary:
        report += "    [Key Metrics (Current / Delta)]\n"
        metrics = ['port_xmit_packets', 'port_rcv_packets', 'port_xmit_data', 'port_rcv_data']
        for key in metrics:
            current_val = current_summary.get(key, 'N/A')
            delta = current_val - previous_summary.get(key, 0) if isinstance(current_val, int) else 'N/A'
            label = key.replace('port_', '').replace('_packets', ' Pkts').replace('_data', ' Data')
            report += f"      {label:<15}: {fmt_num(current_val,18)} / Δ {fmt_num(delta)}\n"
    else:
        report += "    [Key Metrics TX/RX]\n"
        report += "      RDMA Packets:    {} / {}\n".format(
            fmt_num(current_summary.get('port_xmit_packets', 'N/A')),
            fmt_num(current_summary.get('port_rcv_packets', 'N/A')))
        report += "      RDMA Bytes:      {} / {}\n".format(
            fmt_num(current_summary.get('port_xmit_data', 'N/A')),
            fmt_num(current_summary.get('port_rcv_data', 'N/A')))

    report += "    [Potential Issues (Drops/Errors)]\n"
    if issues:
        report += "\n".join(issues)
    else:
        report += "      ✅ No new drop/discard/error counters found."
    report += "\n"
    
    return current_summary, report

def find_latest_log_dir(parent_dir):
    """找到最新的日誌子目錄"""
    if not os.path.exists(parent_dir):
        return None
    subdirs = [d for d in os.listdir(parent_dir) if os.path.isdir(os.path.join(parent_dir, d))]
    subdirs.sort()
    return os.path.join(parent_dir, subdirs[-1]) if subdirs else None

def load_data_from_log_dir(log_dir):
    """從指定的日誌目錄加載所有主機的數據"""
    data = {}
    print(f"Loading previous data from: {log_dir}")
    for log_file in os.listdir(log_dir):
        if log_file.endswith(".log"):
            ip = log_file.split('_')[0]
            print(ip)
            with open(os.path.join(log_dir, log_file), 'r') as f:
                content = f.read()
                summary, _ = analyze_output(content)
                data[ip] = summary
    return data

def compare_host_pkt_num(sender_rdma_helper: RemoteRDMAHelper, receiver_rdma_helper: RemoteRDMAHelper, counter_log_dir: str):
    target_hosts = [sender_rdma_helper, receiver_rdma_helper]
    previous_hosts_data = {}
    last_log_dir = find_latest_log_dir(counter_log_dir)
    if last_log_dir:
        previous_hosts_data = load_data_from_log_dir(last_log_dir)
    else:
        click.echo("WARNING: No previous log directory found. Cannot perform comparison.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_log_dir = os.path.join(counter_log_dir, timestamp)
    os.makedirs(session_log_dir, exist_ok=True)
    click.echo(f"\n本次運行的日誌將保存在: {session_log_dir}\n" + "="*50)

    all_hosts_data = {}

    for rdma_helper in target_hosts:
        hostname = rdma_helper.hostname
        nic = rdma_helper.interface
        ip = rdma_helper.ip
        click.echo(f"Collecting from {hostname} ({nic}) ...")
        output = rdma_helper.get_counter()
        
        logfile = os.path.join(session_log_dir, f"{ip}_{hostname}.log")
        with open(logfile, "w") as f: f.write(output)
            
        if not output.startswith("ERROR"):
            previous_data = previous_hosts_data.get(hostname)
            summary_data, analysis_report = analyze_output(output, previous_data)
            all_hosts_data[ip] = summary_data
            click.echo(analysis_report)
        else:
            click.echo(f"    ERROR: Could not retrieve data for {hostname}. See log for details.")

        click.echo(f" -> Full log saved to {logfile}\n" + "-"*50)
    sender = sender_rdma_helper.ip
    receiver = receiver_rdma_helper.ip
    click.echo("\n" + "="*60)
    click.echo(f"📊 RDMA Packet Delta Comparison: {sender} <--> {receiver}")
    click.echo("="*60)
    sender_curr = all_hosts_data.get(sender)
    receiver_curr = all_hosts_data.get(receiver)
    sender_prev = previous_hosts_data.get(sender)
    receiver_prev = previous_hosts_data.get(receiver)
    if not all([sender_curr, receiver_curr, sender_prev, receiver_prev]):
        click.echo("錯誤：缺少用於比較差值的數據。請確保 sender/receiver 的今昔數據都已成功收集。")
        return None,None
    sender_tx_delta = sender_curr.get('port_xmit_packets', 0) - sender_prev.get('port_xmit_packets', 0)
    sender_rx_delta = sender_curr.get('port_rcv_packets', 0) - sender_prev.get('port_rcv_packets', 0)
    receiver_tx_delta = receiver_curr.get('port_xmit_packets', 0) - receiver_prev.get('port_xmit_packets', 0)
    receiver_rx_delta = receiver_curr.get('port_rcv_packets', 0) - receiver_prev.get('port_rcv_packets', 0)
    
    diff1 = sender_tx_delta - receiver_rx_delta
    diff2 = receiver_tx_delta - sender_rx_delta
    return diff1, diff2

def __get_log_file_path(dir: str, src: str, dst: str):
  return os.path.join(dir, f"{src}-{dst}.log")

def run_check(test_conf_parser: TestConfParser, sender_rdma_helper: RemoteRDMAHelper, receiver_rdma_helper: RemoteRDMAHelper):
    test_conf = test_conf_parser.get()
    check_config = test_conf.applications.remote_rdma.check
    # mkdir for logs
    runtime_log_dir = test_conf.applications.remote_rdma.runtime_log
    remote_log_dir = test_conf.applications.remote_rdma.check.remote_log
    counter_log_dir = check_config.counter_log
    result_dir = check_config.result
    os.makedirs(runtime_log_dir, exist_ok=True)
    os.makedirs(counter_log_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    # prepare commands
    sender_cmd = check_config.cmd.sender
    receiver_cmd = check_config.cmd.receiver
    timeout = check_config.cmd.timeout
    print(f"Running forwarding test between {sender_rdma_helper.ip} and {receiver_rdma_helper.ip} ...")
    # Check counters first
    compare_host_pkt_num(sender_rdma_helper=sender_rdma_helper, receiver_rdma_helper=receiver_rdma_helper, counter_log_dir=counter_log_dir)
    compare_host_pkt_num(sender_rdma_helper=sender_rdma_helper, receiver_rdma_helper=receiver_rdma_helper, counter_log_dir=counter_log_dir)
    # Start receiver first
    base_port = check_config.cmd.base_port
    kill_cmd = check_config.kill_cmd
    sender_rdma_helper.stop_command(kill_cmd=kill_cmd)
    receiver_rdma_helper.stop_command(kill_cmd=kill_cmd)
    time.sleep(5)
    receiver_config = test_conf_parser.get_remote_rdma_cmd_config(receiver_cmd, check_config.cmd.config)
    receiver_config['port'] = base_port
    receiver_runtime_log_path = os.path.join(remote_log_dir, f"forward_test_{receiver_rdma_helper.ip}-{sender_rdma_helper.ip}.log")
    receiver_rdma_helper.run_command(cmd=receiver_cmd, config=receiver_config, timeout=timeout, log_path=receiver_runtime_log_path, is_receiver=True)
    # Then start sender
    sender_config = test_conf_parser.get_remote_rdma_cmd_config(sender_cmd, check_config.cmd.config)
    sender_config['port'] = base_port
    sender_config['receiver_ip'] = receiver_rdma_helper.ip
    print(sender_config)
    sender_runtime_log_path = os.path.join(remote_log_dir, f"forward_test_{sender_rdma_helper.ip}-{receiver_rdma_helper.ip}.log")
    sender_rdma_helper.run_command(cmd=sender_cmd, config=sender_config, timeout=timeout, log_path=sender_runtime_log_path, is_receiver=False)
    sender_rdma_helper.sync_remote_to_local(remote_path=sender_runtime_log_path, local_path=__get_log_file_path(runtime_log_dir, sender_rdma_helper.ip, receiver_rdma_helper.ip))
    # Check counters again
    sender_rdma_helper.stop_command(kill_cmd=kill_cmd)
    receiver_rdma_helper.stop_command(kill_cmd=kill_cmd)
    time.sleep(5)
    diff1, diff2 = compare_host_pkt_num(sender_rdma_helper=sender_rdma_helper, receiver_rdma_helper=receiver_rdma_helper, counter_log_dir=counter_log_dir)
    return diff1, diff2

@cli.command()
def check_one_link(test_conf_parser: TestConfParser):
    """Run link forwarding test (placeholder)"""
    
    click.echo("Running link forwarding test")
    sender = input("Please enter the source host for the test: ")
    receiver = input("Please enter the destination host for the test: ")
    click.echo(f"Source: {sender}, Destination: {receiver}")
    test_conf = test_conf_parser.get()
    remote_user = get_remote_user(
        test_conf.get("applications.remote_rdma.user")
    )
    host_conf = test_conf.config.hosts
    host_conf_parser = HostConfParser(host_conf)
    host_conf_parser.load_conf_file()
    if sender not in host_conf_parser.senders or receiver not in host_conf_parser.receivers:
        click.echo("Error: Source must be a sender and destination must be a receiver as per host config.")
        return
    sender_hostname, sender_interface = host_conf_parser.hosts[sender]['hostname'], host_conf_parser.hosts[sender]['eth']
    receiver_hostname, receiver_interface = host_conf_parser.hosts[receiver]['hostname'], host_conf_parser.hosts[receiver]['eth']
    click.echo(f"Resolved Hostnames - Source: {sender_hostname}, Destination: {receiver_hostname}")
    sender_rdma_helper = RemoteRDMAHelper(
        remote_user=remote_user,
        hostname=sender_hostname,
        interface=sender_interface,
        ip=sender
    )
    receiver_rdma_helper = RemoteRDMAHelper(
        remote_user=remote_user,
        hostname=receiver_hostname,
        interface=receiver_interface,
        ip=receiver
    )
    sender_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
    receiver_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
    diff1, diff2 = run_check(test_conf_parser, sender_rdma_helper, receiver_rdma_helper)
    click.echo(f"Forwarding Test Results:")
    click.echo(f"  {sender} --> {receiver} Difference: {diff1}")
    click.echo(f"  {receiver} --> {sender} Difference: {diff2}")
    
@cli.command()
def check_all_links(test_conf_parser: TestConfParser):
    """Run all-links forwarding test (placeholder)"""
    click.echo("Running all-links forwarding test")
    test_conf = test_conf_parser.get()
    remote_user = get_remote_user(
        test_conf.get("applications.remote_rdma.user")
    )
    host_conf = test_conf.config.hosts
    host_conf_parser = HostConfParser(host_conf)
    host_conf_parser.load_conf_file()
    connection_conf = test_conf.config.connections
    connection_conf_parser = ConnectionConfParser(connection_conf)
    connection_conf_parser.load_conf_file()
    host_rdma_helper_map = generate_ip_helper_map(list(connection_conf_parser.hosts), host_conf_parser.hosts, remote_user)
    # Run tests
    results = []
    for connection in connection_conf_parser.connections:
        receiver_rdma_helper = host_rdma_helper_map[connection['receiver']]
        sender_rdma_helper = host_rdma_helper_map[connection['sender']]
        receiver_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
        sender_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
        click.echo(f"\n=== Testing Link: {sender_rdma_helper.ip} --> {receiver_rdma_helper.ip} ===")
        diff1, diff2 = run_check(test_conf_parser, sender_rdma_helper, receiver_rdma_helper)
        click.echo(f"Forwarding Test Results:")
        results.append((sender_rdma_helper.ip, receiver_rdma_helper.ip, diff1, diff2))
        click.echo(f"  {sender_rdma_helper.ip} --> {receiver_rdma_helper.ip} Difference: {diff1}")
        click.echo(f"  {receiver_rdma_helper.ip} --> {sender_rdma_helper.ip} Difference: {diff2}")
    # Summary
    with open(os.path.join(test_conf.applications.remote_rdma.check.result, "forwarding_test_summary.txt"), "w") as f:
        f.write("Forwarding Test Summary:\n")
        f.write(f"{'Sender':<20} {'Receiver':<20} {'Diff (S->R)':<15} {'Diff (R->S)':<15}\n")
        for sender_ip, receiver_ip, diff1, diff2 in results:
            f.write(f"{sender_ip:<20} {receiver_ip:<20} {diff1:<15} {diff2:<15}\n")

if __name__ == "__main__":
    pass
