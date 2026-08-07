import argparse
import sys
import logging
import os
import signal
from collections import defaultdict
import multiprocessing

from bfrt_helper.bfrt_grpc_client import BfrtGrpcClient
from bfrt_helper.bfrt_grpc_client import gc
from bfrt_helper.bfrt_grpc_client import config_log
from bfrt_helper.port_controller import PortController
from bfrt_helper.packet_replication_controller import PacketReplicationController
from bfrt_helper.buffer_config_controller import *
from conf_parser.yaml_parser import SwitchConfParser
from conf_parser.yaml_parser import TopoConfParser, HostConfParser

from controller import NexthopController, DCQCNController
from check_controller import CheckController



program = 'ecmp'

class ECMPClient(BfrtGrpcClient):
  def __init__(self, program, hostname, switch_conf, topo_conf, host_conf):
    super(ECMPClient, self).__init__(program, hostname, switch_conf, topo_conf, host_conf)
    self.nexthop_init_id = 0
    self.srcToR_to_dstToR_nexthop_id = 0
    self.dstToR_to_srcToR_nexthop_id = 0
    self.srcToR_to_client_nexthop_id = []
    self.dstToR_to_server_nexthop_id = []
    self.srcToR_switch_id = 0
    self.dstToR_switch_id = 1
    self.nexthop_id_port_table = {self.srcToR_switch_id: defaultdict(list), self.dstToR_switch_id: defaultdict(list)}
    self.switch_id_node_table = {self.srcToR_switch_id: None, self.dstToR_switch_id: None}
    self.uplink_dev_ports_table = {}
    self.downlink_dev_ports_table = {}
    self.switch_id_ip_table = {self.srcToR_switch_id: [], self.dstToR_switch_id: []}
    self.port_ip_table = {}
    self.log.info('{} bfrt grpc client init'.format(self.program))
      
  def setup(self, bfrt_ip, bfrt_port, folded_pipe=False):
    super().setup(self.program, bfrt_ip=bfrt_ip, bfrt_port=bfrt_port, folded_pipe=folded_pipe)
    self.port_controller = PortController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
    self.switch_conf_parser = SwitchConfParser(self.switch_conf)
    self.switch_conf_parser.load_conf_file()
    self.__dict__.update(self.switch_conf_parser.parse_dcqcn_config(self.hostname))
    self.__dict__.update(self.switch_conf_parser.parse_multicast_config(self.hostname))
    self.topo_conf_parser = TopoConfParser(self.topo_conf)
    self.topo_conf_parser.load_conf_file()
    self.host_conf_parser = HostConfParser(self.host_conf)
    self.host_conf_parser.load_conf_file()
    self.nexthop_controller = NexthopController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
    self.packet_replication_controller = PacketReplicationController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
    self.DCQCN_controller = DCQCNController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
  
  def init_uplink_table(self):
    for node, info in self.topo_conf_parser.switch_nodes.items():
      if info['loc'] == 'leaf':
        self.uplink_dev_ports_table[node] = []
    for src, src_port, dst, dst_port in self.topo_conf_parser.links:
      if src in self.topo_conf_parser.switch_nodes and self.topo_conf_parser.switch_nodes[src]['loc'] == 'spine':
        fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(dst_port)
        flag, dst_dev_port = self.port_controller.get_dev_port(fp_port, lane)
        if flag is False:
          raise RuntimeError('Port {} is invalid'.format(dst_port))
        elif self.port_controller.check_active(dst_dev_port) is False:
          raise RuntimeError('Port {} does not enable'.format(dst_port))
        self.uplink_dev_ports_table[dst].append(dst_dev_port)
      elif dst in self.topo_conf_parser.switch_nodes and self.topo_conf_parser.switch_nodes[dst]['loc'] == 'spine':
        fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(src_port)
        flag, src_dev_port = self.port_controller.get_dev_port(fp_port, lane)
        if flag is False:
          raise RuntimeError('Port {} is invalid'.format(src_port))
        elif self.port_controller.check_active(src_dev_port) is False:
          raise RuntimeError('Port {} does not enable'.format(src_port))
        self.uplink_dev_ports_table[src].append(src_dev_port)
    print("uplink_dev_ports_table:", self.uplink_dev_ports_table)
        
  def __add_downlink_dev_port(self, node, port):
    fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(port)
    flag, dev_port = self.port_controller.get_dev_port(fp_port, lane)
    if flag is False:
      raise RuntimeError('Port {} is invalid'.format(port))
    elif self.port_controller.check_active(dev_port) is False:
      raise RuntimeError('Port {} does not enable'.format(port))
    self.downlink_dev_ports_table[node].append(dev_port)
  
  def init_downlink_table(self):
    # init downlink dp
    for node, info in self.topo_conf_parser.switch_nodes.items():
      if info['loc'] == 'leaf':
        self.downlink_dev_ports_table[node] = []
    for src, src_port, dst, dst_port in self.topo_conf_parser.links:
      if src in self.host_conf_parser.hosts:
        self.__add_downlink_dev_port(dst, dst_port)
      elif dst in self.host_conf_parser.hosts:
        self.__add_downlink_dev_port(src, src_port)
    print(self.downlink_dev_ports_table)


  def init_ip_table(self):
    def check_port(node, port):
        if node in self.host_conf_parser.hosts:
            fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(port)
            flag, dev_port = self.port_controller.get_dev_port(fp_port, lane)

            if not flag:
                raise RuntimeError(f'Port {port} is invalid')
            if not self.port_controller.check_active(dev_port):
                raise RuntimeError(f'Port {port} does not enable')

            return dev_port
        return None

    for src, src_port, dst, dst_port in self.topo_conf_parser.links:
        src_dev_port = check_port(dst, src_port)
        dst_dev_port = check_port(src, dst_port)
        def add_mapping(node, dev_port):
            if dev_port is not None:
                self.port_ip_table[dev_port] = node
                
        if src in self.host_conf_parser.senders:
            add_mapping(src, dst_dev_port)
        elif src in self.host_conf_parser.receivers:
            add_mapping(src, dst_dev_port)
        elif dst in self.host_conf_parser.senders:
            add_mapping(dst, src_dev_port)
        elif dst in self.host_conf_parser.receivers:
            add_mapping(dst, src_dev_port)
        
  def init_switch_id_node_table(self):
    srcToR_node = set()
    dstToR_node = set()
    for src, _, dst, _ in self.topo_conf_parser.links:
      if src in self.host_conf_parser.senders:
        srcToR_node.add(dst)
      elif dst in self.host_conf_parser.senders:
        srcToR_node.add(src)
      elif src in self.host_conf_parser.receivers:
        dstToR_node.add(dst)
      elif dst in self.host_conf_parser.receivers:
        dstToR_node.add(src)
        
    print("srcToR_node and dstToR_node:")
    print(srcToR_node, dstToR_node)
    if len(srcToR_node) > 1 or len(dstToR_node) > 1:
      raise RuntimeError('topo config is not right, must be one srcToR and one dstToR')
    self.switch_id_node_table[self.srcToR_switch_id] = list(srcToR_node)[0]
    self.switch_id_node_table[self.dstToR_switch_id] = list(dstToR_node)[0]
    
  def init_nexthop_id_port_table(self):
    srcToR_node = self.switch_id_node_table[self.srcToR_switch_id]
    dstToR_node = self.switch_id_node_table[self.dstToR_switch_id]
    self.nexthop_id_port_table[self.srcToR_switch_id][self.nexthop_init_id].extend(self.uplink_dev_ports_table[srcToR_node])
    self.srcToR_to_dstToR_nexthop_id = self.nexthop_init_id
    self.nexthop_init_id += 1
    self.nexthop_id_port_table[self.dstToR_switch_id][self.nexthop_init_id].extend(self.uplink_dev_ports_table[dstToR_node])
    self.dstToR_to_srcToR_nexthop_id = self.nexthop_init_id
    self.nexthop_init_id += 1
    for port in self.downlink_dev_ports_table[srcToR_node]:
        self.nexthop_id_port_table[self.srcToR_switch_id][self.nexthop_init_id].append(port)
        self.srcToR_to_client_nexthop_id.append(self.nexthop_init_id)
        self.nexthop_init_id += 1
    for port in self.downlink_dev_ports_table[dstToR_node]:
        self.nexthop_id_port_table[self.dstToR_switch_id][self.nexthop_init_id].append(port)
        self.dstToR_to_server_nexthop_id.append(self.nexthop_init_id)
        self.nexthop_init_id += 1
  
  def init_nexthop_controller(self):
    srcToR_node = self.switch_id_node_table[self.srcToR_switch_id]
    dstToR_node = self.switch_id_node_table[self.dstToR_switch_id]
    # switch id
    self.nexthop_controller.add_get_switch_id_entries(self.srcToR_switch_id, self.uplink_dev_ports_table[srcToR_node])
    self.nexthop_controller.add_get_switch_id_entries(self.dstToR_switch_id, self.uplink_dev_ports_table[dstToR_node])
    self.nexthop_controller.add_get_switch_id_entries(self.srcToR_switch_id, self.downlink_dev_ports_table[srcToR_node])
    self.nexthop_controller.add_get_switch_id_entries(self.dstToR_switch_id, self.downlink_dev_ports_table[dstToR_node])
    # nexthop_id
    self.nexthop_controller.add_write_nexthop_id_entries(self.host_conf_parser.senders, self.dstToR_to_srcToR_nexthop_id, self.dstToR_switch_id)
    self.nexthop_controller.add_write_nexthop_id_entries(self.host_conf_parser.receivers, self.srcToR_to_dstToR_nexthop_id, self.srcToR_switch_id)
    for nexthop_id, ports in self.nexthop_id_port_table[self.srcToR_switch_id].items():
      if nexthop_id in self.srcToR_to_client_nexthop_id:
        self.nexthop_controller.add_write_nexthop_id_entries([self.port_ip_table[ports[0]]], nexthop_id, self.srcToR_switch_id)
    for nexthop_id, ports in self.nexthop_id_port_table[self.dstToR_switch_id].items():
      if nexthop_id in self.dstToR_to_server_nexthop_id:
        self.nexthop_controller.add_write_nexthop_id_entries([self.port_ip_table[ports[0]]], nexthop_id, self.dstToR_switch_id)
    # nexthop table
    for nexthop_id, ports in self.nexthop_id_port_table[self.srcToR_switch_id].items():
      print(ports)
      self.nexthop_controller.add_nexthop_table_entries(nexthop_id, ports)
    for nexthop_id, ports in self.nexthop_id_port_table[self.dstToR_switch_id].items():
      self.nexthop_controller.add_nexthop_table_entries(nexthop_id, ports)
      
  def init_DCQCN_controller(self):
    self.DCQCN_controller.add_entries(dcqcn_k_max=self.DCQCN_K_MAX, dcqcn_k_min=self.DCQCN_K_MIN, dcqcn_p_max=self.DCQCN_P_MAX, seed_range_max=self.SEED_RANGE_MAX);
      
  def init_multicast(self):
    self.packet_replication_controller.add_multicast_group(self.MCAST_GRP_ID)
    port_list = []
    for _, ports in self.downlink_dev_ports_table.items():
      port_list.extend(ports)
    rids_and_ports = [(self.RID + index, port)
                      for index, port in enumerate(port_list)]
    flag, msg = self.packet_replication_controller.add_multicast_nodes(self.MCAST_GRP_ID, rids_and_ports)
    return flag, msg
  
class BufferConfigClient(BfrtGrpcClient):
  def __init__(self, program, hostname, switch_conf, topo_conf, host_conf, pipe_id):
    super(BufferConfigClient, self).__init__(program, hostname, switch_conf, topo_conf, host_conf)
    self.pipe_id = pipe_id
  
  def setup(self, bfrt_ip, bfrt_port, client_id, folded_pipe=False):
    super().setup(self.program, bfrt_ip=bfrt_ip, bfrt_port=bfrt_port, folded_pipe=folded_pipe, pipe_id=self.pipe_id, client_id=client_id)
    self.port_controller = PortController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
    self.ingress_buffer_controller = IngressBufferConfigController(target=self.target, gc=gc, bfrt_info=self.bfrt_info, arch='tf1')
    self.egress_buffer_controller = EgressBufferConfigController(target=self.target, gc=gc, bfrt_info=self.bfrt_info, arch='tf1')
    self.check_controller = CheckController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
    self.switch_conf_parser = SwitchConfParser(self.switch_conf)
    self.switch_conf_parser.load_conf_file()
    self.__dict__.update(self.switch_conf_parser.parse_buffer_config(self.hostname))
    self.topo_conf_parser = TopoConfParser(self.topo_conf)
    self.topo_conf_parser.load_conf_file()
    self.host_conf_parser = HostConfParser(self.host_conf)
    self.host_conf_parser.load_conf_file()
  
  def config_lossless_buffer(self):
    switch = self.switch_conf_parser.switches[self.hostname]
    ports = switch['ports']
    dev_port_map = {}
    for idx, (port, _) in enumerate(ports.items(), start=1):  # start=0 可以改成 1
      fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(port)
      _, dev_port = self.port_controller.get_dev_port(fp_port, lane)
      dev_port_map[idx] = dev_port
    for ppg_id, dev_port in dev_port_map.items():
      if (dev_port >> 7) == self.pipe_id:
        if self.PFC_ENABLE:
          self.port_controller.enable_pfc(dev_port=dev_port)
        self.ingress_buffer_controller.add_ppg_cfg_table_entry(dev_port, ppg_id, 0, self.guaranteed_cells, 0, self.ingress_buffer_cells, self.PFC_ENABLE, self.skid_max_cells, self.ingress_dynamic_baf)
        if self.PFC_ENABLE:
          self.ingress_buffer_controller.mod_port_flowcontrol_entry(dev_port, 'PFC', 'PFC')
        self.egress_buffer_controller.mod_pool_cfg_table(0, self.egress_buffer_cells)
        pg_id, pg_queue = self.check_controller.get_pg_id_and_pg_queue(dev_port, 0)
        # print(dev_port, pg_id, pg_queue)
        self.egress_buffer_controller.mod_queue_buffer_shared_pool_table(pg_id, pg_queue, self.guaranteed_cells, 0, self.egress_buffer_cells, self.egress_dynamic_baf)
        self.egress_buffer_controller.mod_queue_sched_cfg_table(pg_id, pg_queue, dwrr_weight=600)

def run_ecmp_client(program, args):
  # init grpc client
  ecmp_client = ECMPClient(program, args.hostname, args.switches, args.topo, args.hosts)
  ecmp_client.setup(args.bfrt_ip, args.bfrt_port)

  # init port
  port_list = ecmp_client.switch_conf_parser.parse_ports(hostname=args.hostname)
  if port_list is not None:
    ecmp_client.port_controller.add_ports(port_list=port_list)
  else:
    ecmp_client.critical_error("Invalid format detected in {}. Please review the configuration.".format(args.switches))
  
  ecmp_client.init_uplink_table()
  ecmp_client.init_downlink_table()
  ecmp_client.init_switch_id_node_table()
  ecmp_client.init_nexthop_id_port_table()
  ecmp_client.init_ip_table()
  ecmp_client.init_nexthop_controller()
  ecmp_client.init_multicast()
  # ecmp_client.init_DCQCN_controller()
 
def run_buffer_client(program, args, pipe_id):
    client = BufferConfigClient(program, args.hostname, args.switches, args.topo, args.hosts, pipe_id)
    client.setup(args.bfrt_ip, args.bfrt_port, pipe_id + 1)
    client.config_lossless_buffer()

if __name__ == '__main__':
  # parse argument
  argparser = argparse.ArgumentParser(description="{} controller.".format(program))
  argparser.add_argument(
        '--bfrt-ip',
        type=str,
        default='127.0.0.1',
        help='Name/address of the BFRuntime server. Default: 127.0.0.1')
  argparser.add_argument('--bfrt-port',
        type=int,
        default=50052,
        help='Port of the BFRuntime server. Default: 50052')
  argparser.add_argument(
        '--hostname',
        type=str,
        help='Switch hostname. e.g. tf_sw1')
  argparser.add_argument(
        '--switches',
        type=str,
        help='YAML file describing switch configure.')
  argparser.add_argument(
        '--topo',
        type=str,
        help='YAML file describing topo.')
  argparser.add_argument(
        '--hosts',
        type=str,
        help='YAML file describing hosts.')
  argparser.add_argument('--log-level',
        default='INFO',
        choices=['ERROR', 'WARNING', 'INFO', 'DEBUG'],
        help='Default: INFO')

  args = argparser.parse_args()
  
  # Configure logging
  config_log(args.log_level, '{}.log'.format(program))
  
  # 顺序执行：native_afc_client -> buffer_config_clients
  processes = []
  # 第一个进程：native_afc
  processes.append(multiprocessing.Process(
      target=run_ecmp_client,
      args=(program, args)
  ))
  # buffer_config_clients
  for pipe_id in range(4):
      processes.append(multiprocessing.Process(
          target=run_buffer_client,
          args=(program, args, pipe_id)
      ))
  # 串行启动并等待结束
  for p in processes:
      p.start()
      p.join()
