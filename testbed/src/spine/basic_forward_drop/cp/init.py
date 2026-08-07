import argparse
import sys
import logging
import os
import signal
import multiprocessing

from bfrt_helper.bfrt_grpc_client import BfrtGrpcClient
from bfrt_helper.bfrt_grpc_client import gc
from bfrt_helper.bfrt_grpc_client import config_log
from bfrt_helper.port_controller import PortController
from conf_parser.yaml_parser import SwitchConfParser, TopoConfParser, HostConfParser
from forward_controller import ForwardController
from bfrt_helper.buffer_config_controller import *
from check_controller import CheckController
program = 'basic_forward_drop'


class BasicForwardClient(BfrtGrpcClient):
    def __init__(self, program, hostname, switch_conf, topo_conf, host_conf):
        super(BasicForwardClient, self).__init__(program, hostname, switch_conf, topo_conf, host_conf)
        self.log.info('basic forward bfrt grpc client init')

    def setup(self, bfrt_ip, bfrt_port, folded_pipe=False):
        super(BasicForwardClient, self).setup(self.program, bfrt_ip=bfrt_ip,
                                              bfrt_port=bfrt_port, folded_pipe=folded_pipe)

        self.port_controller = PortController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
        self.forward_controller = ForwardController(target=self.target, gc=gc, bfrt_info=self.bfrt_info)
        self.switch_conf_parser = SwitchConfParser(self.switch_conf)
        self.switch_conf_parser.load_conf_file()
        self.topo_conf_parser = TopoConfParser(self.topo_conf)
        self.topo_conf_parser.load_conf_file()
        self.host_conf_parser = HostConfParser(self.host_conf)
        self.host_conf_parser.load_conf_file()

    def add_forward(self):
        nodes = [node for node, info in self.topo_conf_parser.switch_nodes.items()
                 if info['hostname'] == args.hostname]
        dev_port_links_table = {}
        for node in nodes:
            dev_port_links_table[node] = []

        for src, src_port, to, to_port in self.topo_conf_parser.links:
            if src in nodes:
                dev_port_links_table[src].append(src_port)
            if to in nodes:
                dev_port_links_table[to].append(to_port)

        dev_port_links_list = []
        for node, from_to in dev_port_links_table.items():
            if len(from_to) < 2:
                raise RuntimeError('{} configuration has fault, port num < 2'.format(node))
            if from_to[0] == from_to[1]:
                raise RuntimeError('{} configuration has fault, recirculate'.format(node))

            fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(from_to[0])
            flag, src_dev_port = self.port_controller.get_dev_port(fp_port, lane)
            if flag is False:
                raise RuntimeError('Port {} is invalid'.format(from_to[0]))
            elif self.port_controller.check_active(src_dev_port) is False:
                raise RuntimeError('Port {} does not enable'.format(from_to[0]))

            fp_port, lane = self.switch_conf_parser.get_fp_port_and_lane(from_to[1])
            flag, dst_dev_port = self.port_controller.get_dev_port(fp_port, lane)
            if flag is False:
                raise RuntimeError('Port {} is invalid'.format(from_to[1]))
            elif self.port_controller.check_active(dst_dev_port) is False:
                raise RuntimeError('Port {} does not enable'.format(from_to[1]))

            dev_port_links_list.append((src_dev_port, dst_dev_port))
            dev_port_links_list.append((dst_dev_port, src_dev_port))

        print(dev_port_links_list)
        self.forward_controller.add_entries(dev_port_links_list)


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
        self.egress_buffer_controller.mod_pool_cfg_table(1, self.egress_buffer_cells)
        pg_id, pg_queue = self.check_controller.get_pg_id_and_pg_queue(dev_port, 0)
        # print(dev_port, pg_id, pg_queue)
        self.egress_buffer_controller.mod_queue_buffer_shared_pool_table(pg_id, pg_queue, self.guaranteed_cells, 1, self.egress_buffer_cells, self.egress_dynamic_baf)
        self.egress_buffer_controller.mod_queue_sched_cfg_table(pg_id, pg_queue, dwrr_weight=600)

def run_buffer_client(program, args, pipe_id):
    client = BufferConfigClient(program, args.hostname, args.switches, args.topo, args.hosts, pipe_id)
    client.setup(args.bfrt_ip, args.bfrt_port, pipe_id + 1)
    client.config_lossless_buffer()

def run_basic_forward_client(program, args):
    # init grpc client
    basic_forward_client = BasicForwardClient(program, args.hostname, args.switches, args.topo, args.hosts)
    basic_forward_client.setup(args.bfrt_ip, args.bfrt_port)

    # init port
    port_list = basic_forward_client.switch_conf_parser.parse_ports(hostname=args.hostname)
    if port_list is not None:
        basic_forward_client.port_controller.add_ports(port_list=port_list)
    else:
        basic_forward_client.critical_error("Invalid format detected in {}. Please review the configuration.".format(args.switches))

    # init forward controller
    basic_forward_client.add_forward()

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
    processes.append(multiprocessing.Process(
        target=run_basic_forward_client,
        args=(program, args)
    ))
    
    for pipe_id in range(4):
      processes.append(multiprocessing.Process(
          target=run_buffer_client,
          args=(program, args, pipe_id)
      ))
    # 第一个进程：native_afc
    
    # 串行启动并等待结束
    for p in processes:
        p.start()
        p.join()

    # Flush log, stdout, stderr
    sys.stdout.flush()
    sys.stderr.flush()
    logging.shutdown()

    # Exit
    os.kill(os.getpid(), signal.SIGTERM)
