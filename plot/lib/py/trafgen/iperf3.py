import json
import pandas as pd


class Iperf3Json(object):
    ''' Read and process the json logs of iperf3

    Attributes:
        json_fname: The json log file name
        json_data: A dictionary contains json data
        flows: A dictionary containing meta data about flows
        throughput: A pandas.DataFrame containing the sum throughput samples
        throughput_per_flow:
            A dictionary containing the throughput samples of each flow
    '''
    def __init__(self, fname):
        self.json_fname = fname
        json_str = ''
        with open(fname) as fp:
            start = False
            for line in fp:
                if line == '{\n':
                    start = True
                if start:
                    json_str += line
                if start and line == '}\n':
                    break
        self.json_data = json.loads(json_str)
        self.read_meta()
        self.read_goodput()
        self.read_summary()

    def read_meta(self):
        self.flows = {}
        for flow in self.json_data['start']['connected']:
            self.flows[flow['socket']] = flow
        self.meta = self.json_data['start']['test_start']
        self.protocol = self.meta['protocol']
        start_time = pd.to_datetime(
            self.json_data['start']['timestamp']['time']
        )
        start_time = start_time.tz_convert('Asia/Shanghai').tz_localize(None)
        self.start_time = start_time
        self.end_time = start_time + pd.Timedelta(self.meta['duration'], unit='sec')

    def read_summary(self):
        if self.protocol == 'TCP':
            self.read_tcp_summary()
        elif self.protocol == 'UDP':
            self.read_udp_summary()

    def read_tcp_summary(self):
        if 'steams' not in self.json_data['end']:
            return
        sum_send_per_flow = {}
        sum_recv_per_flow = {}
        # the connection is unexpectedly closed
        for flow in self.json_data['end']['streams']:
            sock = flow['sender']['socket']
            sum_send_per_flow[sock] = flow['sender']
            sock = flow['receiver']['socket']
            sum_recv_per_flow[sock] = flow['receiver']
        self.sum_send_per_flow = sum_send_per_flow
        self.sum_recv_per_flow = sum_recv_per_flow
        self.sum_sent = self.json_data['end']['sum_sent']
        self.sum_received = self.json_data['end']['sum_received']

    def read_udp_summary(self):
        if 'steams' not in self.json_data['end']:
            return
        sum_udp_per_flow = {}
        for flow in self.json_data['end']['streams']:
            sock = flow['udp']['socket']
            sum_udp_per_flow[sock] = flow['udp']
        self.sum_udp_per_flow = sum_udp_per_flow
        self.sum_udp = self.json_data['end']['sum']

    def read_goodput(self):
        throughput_per_flow = {}
        throughput = []
        for item in self.json_data['intervals']:
            for flow in item['streams']:
                sock = flow['socket']
                if sock not in throughput_per_flow:
                    throughput_per_flow[sock] = []
                throughput_per_flow[sock].append(flow)
            throughput.append(item['sum'])
        throughput = pd.DataFrame(throughput)
        throughput['time'] = (throughput['start'] + throughput['end']) / 2
        for flow in throughput_per_flow:
            gpt = pd.DataFrame(throughput_per_flow[flow])
            gpt['time'] = (gpt['start'] + gpt['end']) / 2
            throughput_per_flow[flow] = gpt
        self.throughput = throughput
        self.throughput_per_flow = throughput_per_flow

    def get_retrans_rate(self, mtu=1448):
        if self.protocol != 'TCP':
            return None
        n_retrans = self.sum_sent['retransmits']
        n_packets = self.sum_sent['bytes']/1448
        return n_retrans/n_packets

    def get_fairness_index(self):
        throughputs = []
        if self.protocol == 'TCP':
            sum_per_flow = self.sum_recv_per_flow
        elif self.protocol == 'UDP':
            sum_per_flow = self.sum_udp_per_flow
        else:
            return None
        for sock in self.sum_per_flow:
            throughputs.append(self.sum_per_flow[sock]['bits_per_second'])
        throughputs = pd.Series(throughputs)
        return (throughputs.mean())**2 / (throughputs**2).mean()
