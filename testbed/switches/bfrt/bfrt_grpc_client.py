#  Copyright 2021 Intel-KAUST-Microsoft
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
import sys
import glob
import logging
import signal


bfrt_location = '{}/lib/python*/site-packages/tofino'.format(
    os.environ['SDE_INSTALL'])
sys.path.append(glob.glob(bfrt_location)[0])
bfrt_grpc_location = '{}/lib/python*/site-packages/tofino/bfrt_grpc'.format(
    os.environ['SDE_INSTALL'])
sys.path.append(glob.glob(bfrt_grpc_location)[0])

import bfrt_grpc.client as gc

def config_log(log_level, filename):
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        sys.exit('Invalid log level: {}'.format(log_level))
    logformat = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(filename=filename,
                        filemode='w',
                        level=numeric_level,
                        format=logformat,
                        datefmt='%H:%M:%S')

class BfrtGrpcClient(object):
    """Base class for BFRT gRPC client used to control a Tofino-based switch.

    This class handles the initialization and connection to the BFRuntime gRPC
    server, loads the P4 pipeline, and manages multicast group configurations.

    It provides helper methods for logging critical errors and for setting up
    the control interface to the switch via the gRPC protocol.

    Attributes:
        log (logging.Logger): Logger instance for this client.
        all_ports_mgid (int): Multicast group ID used to target all ports.
        all_ports_initial_rid (int): Initial replication ID used with all_ports_mgid.
        multicast_groups (dict): Maps multicast group IDs to replication entries.

        dev (int): The device ID (default is 0).
        target (gc.Target): The target used to address all pipes in the device.
        folded_pipe (bool): Whether the pipeline is configured in folded mode.
        bfrt_info (gc.BfRtInfo): Object containing table metadata for the loaded program.
    """
    def __init__(self, program, hostname, switch_conf, topo_conf, host_conf):
        super().__init__()
        self.program = program
        self.hostname = hostname
        self.switch_conf = switch_conf
        self.topo_conf = topo_conf
        self.host_conf = host_conf
        self.log = logging.getLogger(__name__)

        # Set all nodes MGID
        self.all_ports_mgid = 0x8000
        self.all_ports_initial_rid = 0x8000

        # Multicast group ID -> replication ID (= node ID) -> port
        self.multicast_groups = {self.all_ports_mgid: {}}

    def critical_error(self, msg):
        self.log.critical(msg)
        print(msg, file=sys.stderr)
        logging.shutdown()
        #sys.exit(1)
        os.kill(os.getpid(), signal.SIGTERM)
    
    def setup(self,
              program,
              bfrt_ip,
              bfrt_port,
              folded_pipe=False,
              pipe_id=0xFFFF,
              client_id=0):
        """Initializes connection to the BFRuntime server and binds the P4 pipeline.

        This method connects to the specified BFRT gRPC server, binds the
        specified P4 program, and retrieves table metadata.

        Args:
            program (str): The name of the P4 program to bind.
            bfrt_ip (str): IP address of the BFRT server.
            bfrt_port (int): Port number of the BFRT server.
            folded_pipe (bool, optional): Whether to use folded pipe mode. Defaults to False.

        Raises:
            SystemExit: On failure to connect or bind the P4 program.
        """
        # Device 0
        self.dev = 0
        # Target all pipes
        self.target = gc.Target(self.dev, pipe_id=pipe_id)
        # Folded pipe
        self.folded_pipe = folded_pipe

        # Connect to BFRT server
        try:
            interface = gc.ClientInterface('{}:{}'.format(bfrt_ip, bfrt_port),
                                           client_id=client_id,
                                           device_id=self.dev)
        except RuntimeError as re:
            msg = re.args[0] % re.args[1]
            self.critical_error(msg)
        else:
            self.log.info('Connected to BFRT server {}:{}'.format(
                bfrt_ip, bfrt_port))

        try:
            interface.bind_pipeline_config(program)
        except gc.BfruntimeForwardingRpcException:
            self.critical_error('P4 program {} not found!'.format(program))

        try:
            # Get all tables for program
            self.bfrt_info = interface.bfrt_info_get(program)
            
        except KeyboardInterrupt:
            self.critical_error('Stopping controller.')
        except Exception as e:
            self.log.exception(e)
            self.critical_error('Unexpected error. Stopping controller.')