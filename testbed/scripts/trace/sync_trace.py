#!/usr/bin/python3
from conf_parser.yaml_parser import TestConfParser, HostConfParser
from common.remote_rdma_helper import RemoteRDMAHelper, generate_ip_helper_map
from common.repo_helper import get_remote_user
import click

@click.group()
def cli():
  pass

@cli.command()
def sync_trace(test_conf_parser: TestConfParser):
	test_conf = test_conf_parser.get()
	remote_user = get_remote_user(
		test_conf.get("applications.remote_rdma.user")
	)
	host_conf_path = test_conf.config.hosts
	host_conf_parser = HostConfParser(host_conf_path)
	host_conf_parser.load_conf_file()
	sender_rdma_helper_map = generate_ip_helper_map(host_conf_parser.senders, host_conf_parser.hosts, remote_user)
	already_sync_hostname = set()
	for _, sender_rdma_helper in sender_rdma_helper_map.items():
		hostname = sender_rdma_helper.hostname
		if hostname not in already_sync_hostname:
			sender_rdma_helper.sync_local_to_remote(test_conf.applications.gen_trace.local_path, test_conf.applications.gen_trace.remote_path)
			already_sync_hostname.add(hostname)
