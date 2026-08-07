#!/usr/bin/python3
import yaml
import os
import sys
import time
import argparse
import click
import threading
from conf_parser.yaml_parser import TopoConfParser, TestConfParser, HostConfParser, TestConfig, ConnectionConfParser
from common.remote_rdma_helper import RemoteRDMAHelper, generate_ip_helper_map
from common.repo_helper import get_remote_user

@click.group()
def cli():
    """Remote RDMA test tool with various test commands"""
    pass
  
def __get_log_file_path(dir: str, src: str, dst: str):
  return os.path.join(dir, f"{src}-{dst}.log")

def __start_thread(test_conf_parser: TestConfParser, sender_rdma_helper: RemoteRDMAHelper, receiver_rdma_helper: RemoteRDMAHelper, port: int):
    test_conf = test_conf_parser.get()
    remote_rdma_conf = test_conf.applications.remote_rdma
    local_log_dir = remote_rdma_conf.test.local_log
    remote_log_dir = remote_rdma_conf.test.remote_log
    cmd = test_conf.applications.remote_rdma.test.cmd
    sender_cmd = cmd.sender
    receiver_cmd = cmd.receiver
    timeout = cmd.timeout
    # start receiver first
    receiver_config = test_conf_parser.get_remote_rdma_cmd_config(receiver_cmd, cmd.config)
    receiver_config['port'] = port
    receiver_runtime_log_path = __get_log_file_path(remote_log_dir, receiver_rdma_helper.ip, sender_rdma_helper.ip)
    receiver_rdma_helper.run_command(cmd=receiver_cmd, config=receiver_config, timeout=timeout, log_path=receiver_runtime_log_path, is_receiver=True)
    # then start sender
    time.sleep(2)  # wait for receiver to be ready
    sender_config = test_conf_parser.get_remote_rdma_cmd_config(sender_cmd, cmd.config)
    sender_config['port'] = port
    sender_config['receiver_ip'] = receiver_rdma_helper.ip
    try:
      sender_config['trace'] = os.path.join(remote_rdma_conf.test.remote_trace_dir, f'{sender_rdma_helper.ip}-{receiver_rdma_helper.ip}.trace')
    except AttributeError:
      print("no trace file")
    sender_runtime_log_path = __get_log_file_path(remote_log_dir, sender_rdma_helper.ip, receiver_rdma_helper.ip)
    sender_rdma_helper.run_command(cmd=sender_cmd, config=sender_config, timeout=timeout, log_path=sender_runtime_log_path, is_receiver=False)
    # stop
    kill_cmd = test_conf.applications.remote_rdma.test.kill_cmd
    # sender_rdma_helper.stop_command(kill_cmd=kill_cmd)
    sender_rdma_helper.sync_remote_to_local(remote_path=sender_runtime_log_path, local_path=__get_log_file_path(local_log_dir, sender_rdma_helper.ip, receiver_rdma_helper.ip))
    # receiver_rdma_helper.sync_remote_to_local(remote_path=receiver_runtime_log_path, local_path=__get_log_file_path(local_log_dir, receiver_rdma_helper.ip, sender_rdma_helper.ip))

@cli.command()
def sequential_start(test_conf_parser: TestConfParser):
  test_conf = test_conf_parser.get()
  os.makedirs(test_conf.applications.remote_rdma.test.local_log, exist_ok=True)
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
  port = test_conf.applications.remote_rdma.test.cmd.base_port
  # config mlxreg
  for host_rdma_helper in host_rdma_helper_map.values():
    host_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
    for reg_name, option_table in host_conf_parser.hosts[host_rdma_helper.ip]["mlxreg"].items():
      host_rdma_helper.config_mlxreg(reg_name=reg_name, option_table=option_table)
  # start test
  for connection in connection_conf_parser.connections:
    receiver_rdma_helper = host_rdma_helper_map[connection['receiver']]
    sender_rdma_helper = host_rdma_helper_map[connection['sender']]
    port = port + 1
    __start_thread(test_conf_parser, sender_rdma_helper, receiver_rdma_helper, port)
      
@cli.command()
def concurrent_start(test_conf_parser: TestConfParser):
  test_conf = test_conf_parser.get()
  os.makedirs(test_conf.applications.remote_rdma.test.local_log, exist_ok=True)
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
  threads = []
  port = test_conf.applications.remote_rdma.test.cmd.base_port
  kill_cmd = test_conf.applications.remote_rdma.test.kill_cmd
  # config mlxreg
  for host_rdma_helper in host_rdma_helper_map.values():
    host_rdma_helper.stop_command(kill_cmd=kill_cmd)
    host_rdma_helper.get_mellanox_info(host_conf_parser=host_conf_parser)
    for reg_name, option_table in host_conf_parser.hosts[host_rdma_helper.ip]["mlxreg"].items():
      host_rdma_helper.config_mlxreg(reg_name=reg_name, option_table=option_table)
  # start test
  for connection in connection_conf_parser.connections:
    receiver_rdma_helper = host_rdma_helper_map[connection['receiver']]
    sender_rdma_helper = host_rdma_helper_map[connection['sender']]
    port = port + 1
    thread = threading.Thread(target=__start_thread, args=(test_conf_parser, sender_rdma_helper, receiver_rdma_helper, port,))
    thread.start()
    threads.append(thread)
  for thread in threads:
    thread.join()
    
if __name__ == '__main__':
  pass
