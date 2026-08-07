#!/usr/bin/python3
import sys
import random
import math
import heapq
import os
from .custom_rand import CustomRand
from conf_parser.yaml_parser import TestConfParser, HostConfParser, ConnectionConfParser
from common.remote_rdma_helper import RemoteRDMAHelper, generate_ip_helper_map
import click


def translate_bandwidth(b):
	if b == None:
		return None
	if type(b)!=str:
		return None
	if b[-1] == 'G':
		return float(b[:-1])*1e9
	if b[-1] == 'M':
		return float(b[:-1])*1e6
	if b[-1] == 'K':
		return float(b[:-1])*1e3
	return float(b)

def poisson(lam):
	return -math.log(1-random.random())*lam

@click.group()
def cli():
  pass

@cli.command()
def gen_trace_from_host(test_conf_parser: TestConfParser):
	"""Generate traffic traces based on host configuration.

	This function generates traffic traces for all sender-receiver pairs
	derived from the host configuration file. Each sender generates flows
	to randomly selected receivers based on a Poisson arrival process.

	Args:
		test_conf_parser: Parser containing the test configuration.
	"""
	test_conf = test_conf_parser.get()
	
	trace_gen_config = test_conf.applications.gen_trace
	random.seed(42)
	base_t = 2000000000 # 2000000000
	path = trace_gen_config.local_path
	os.makedirs(path, exist_ok=True)
	
	load = float(trace_gen_config.load)
	bandwidth = translate_bandwidth(trace_gen_config.bandwidth)
	time = float(trace_gen_config.time)*1e9 # translates to ns
	if bandwidth == None:
		print("bandwidth format incorrect")
		sys.exit(0)

	fileName = trace_gen_config.cdf
	file = open(fileName,"r")
	lines = file.readlines()
	# read the cdf, save in cdf as [[x_i, cdf_i] ...]
	cdf = []
	for line in lines:
		x,y = map(float, line.strip().split(' '))
		cdf.append([x,y])

	# create a custom random generator, which takes a cdf, and generate number according to the cdf
	customRand = CustomRand()
	if not customRand.setCdf(cdf):
		print("Error: Not valid cdf")
		sys.exit(0)

	host_conf_path = test_conf.config.hosts
	host_conf_parser = HostConfParser(host_conf_path)
	host_conf_parser.load_conf_file()
	
	flow_data = {}
	sender_list = []
	receiver_list = []

	for sender in host_conf_parser.senders:
			sender_list.append(sender)
	for receiver in host_conf_parser.receivers:
		receiver_list.append(receiver)

	for sender in sender_list:
		for receiver in receiver_list:
			flow_data[(sender, receiver)] = []


	avg = customRand.getAvg()
	avg_inter_arrival = 1 / (bandwidth * load / 8.0 / avg) * 1_000_000_000
	n_flow = 0

	# === 初始化事件队列（最小堆）===
	host_list = [(base_t + int(poisson(avg_inter_arrival)), sender) for sender in sender_list]
	heapq.heapify(host_list)

	# === 生成流量事件 ===
	while host_list:	
			t, sender = host_list[0]
			inter_t = int(poisson(avg_inter_arrival))
			receiver = random.choice(receiver_list)
			next_time = t + inter_t			
			if next_time > time + base_t:
				heapq.heappop(host_list)
			else:
				size = max(1, int(customRand.rand()))  # 确保 size >= 1
				n_flow += 1
				# 缓存流量数据
				flow_data[(sender, receiver)].append((size, next_time))
				# 更新堆
				heapq.heapreplace(host_list, (next_time, sender))

	# === 最后统一写入所有 trace 文件 ===

	for (sender, receiver), flows in flow_data.items():
		trace_file_name = f'{sender}-{receiver}.trace'
		filepath = os.path.join(path, trace_file_name)
		with open(filepath, 'w') as f:
			f.write(f"{len(flows)}\n")  # 第一行：flow 数量
			for size, timestamp in flows:
				f.write(f"{size} {timestamp}\n")


@cli.command()
def gen_trace_from_connection(test_conf_parser: TestConfParser):
	"""Generate traffic traces based on connection configuration.

	This function generates traffic traces for specific sender-receiver pairs
	defined in the connection configuration file. Each connection independently
	generates flows based on a Poisson arrival process.

	Args:
		test_conf_parser: Parser containing the test configuration.
	"""
	test_conf = test_conf_parser.get()

	# Load connection configuration
	connection_conf_path = test_conf.config.connections
	if connection_conf_path is None:
		print("Error: No connection configuration path specified in test config")
		sys.exit(1)

	connection_conf_parser = ConnectionConfParser(connection_conf_path)
	connection_conf_parser.load_conf_file()

	if not connection_conf_parser.connections:
		print("Error: No connections found in configuration")
		sys.exit(1)

	print(f"Loaded {len(connection_conf_parser.connections)} connections from {connection_conf_path}")

	trace_gen_config = test_conf.applications.gen_trace
	random.seed(42)
	base_t = 2000000000
	path = trace_gen_config.local_path
	os.makedirs(path, exist_ok=True)

	load = float(trace_gen_config.load)
	bandwidth = translate_bandwidth(trace_gen_config.bandwidth)
	time = float(trace_gen_config.time)*1e9  # translates to ns
	if bandwidth is None:
		print("bandwidth format incorrect")
		sys.exit(0)

	fileName = trace_gen_config.cdf
	file = open(fileName, "r")
	lines = file.readlines()
	# read the cdf, save in cdf as [[x_i, cdf_i] ...]
	cdf = []
	for line in lines:
		x, y = map(float, line.strip().split(' '))
		cdf.append([x, y])

	# create a custom random generator, which takes a cdf, and generate number according to the cdf
	customRand = CustomRand()
	if not customRand.setCdf(cdf):
		print("Error: Not valid cdf")
		sys.exit(0)

	# Initialize flow_data for each connection
	flow_data = {}
	connections = []
	for conn in connection_conf_parser.connections:
		sender = conn['sender']
		receiver = conn['receiver']
		connections.append((sender, receiver))
		flow_data[(sender, receiver)] = []

	if not connections:
		print("Error: No valid connections found")
		sys.exit(1)

	print(f"Generating traffic for {len(connections)} connections")

	avg = customRand.getAvg()
	avg_inter_arrival = 1 / (bandwidth * load / 8.0 / avg) * 1_000_000_000
	n_flow = 0

	# === Initialize event queue with each connection as a unit ===
	# Each connection independently generates traffic
	conn_list = [(base_t + int(poisson(avg_inter_arrival)), sender, receiver)
				 for (sender, receiver) in connections]
	heapq.heapify(conn_list)

	# === Generate traffic events ===
	while conn_list:
		t, sender, receiver = conn_list[0]
		inter_t = int(poisson(avg_inter_arrival))
		next_time = t + inter_t
		if next_time > time + base_t:
			heapq.heappop(conn_list)
		else:
			size = max(1, int(customRand.rand()))  # Ensure size >= 1
			n_flow += 1
			# Cache flow data for this specific connection
			flow_data[(sender, receiver)].append((size, next_time))
			# Update heap
			heapq.heapreplace(conn_list, (next_time, sender, receiver))

	# === Write all trace files ===
	for (sender, receiver), flows in flow_data.items():
		trace_file_name = f'{sender}-{receiver}.trace'
		filepath = os.path.join(path, trace_file_name)
		with open(filepath, 'w') as f:
			f.write(f"{len(flows)}\n")  # First line: flow count
			for size, timestamp in flows:
				f.write(f"{size} {timestamp}\n")

	print(f"Generated {n_flow} flows across {len(flow_data)} trace files")

