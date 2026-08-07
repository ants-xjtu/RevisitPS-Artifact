import yaml
import re
from .conf_parser import ConfParser

from dataclasses import dataclass, field, make_dataclass, is_dataclass
from typing import Any, Dict, List, get_origin, get_args
from jinja2 import Template, Environment, meta

# ================================================================
#  Auto Getter Injection
# ================================================================
def inject_getter(obj):
    """Injects a .get("a.b.c") method into the created dataclass instance."""
    def getter(path: str, default=None):
        parts = path.split(".")
        cur = obj
        for p in parts:
            if not hasattr(cur, p):
                return default
            cur = getattr(cur, p)
        return cur

    setattr(obj, "get", getter)
    return obj

def process_scalar_string(value: str):
    """
    将原始字符串自动转换为对应的 Python 类型。
    """
    if not isinstance(value, str):
        return value  # 非字符串不处理

    v = value.strip()

    # ---- bool ----
    low = v.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False

    # ---- int ----
    if re.fullmatch(r"[+-]?\d+", v):
        try:
            return int(v)
        except ValueError:
            pass

    # ---- float ----
    if re.fullmatch(r"[+-]?\d+\.\d+", v) or re.fullmatch(r"[+-]?\d+\.\d*[eE][+-]?\d+", v):
        try:
            return float(v)
        except ValueError:
            pass

    # ---- empty → keep empty ----
    if v == "":
        return ""

    # ---- default: keep string ----
    return v

# ================================================================
#  Auto YAML → Dataclass recursive loader
# ================================================================
def yaml_to_dataclass(name: str, data: Any):
    """Recursively transform YAML dict/list/scalar → nested dataclasses."""

    # -----------------------
    # Case 1: simple scalar
    # -----------------------
    if not isinstance(data, (dict, list)):
        if isinstance(data, str):
            return process_scalar_string(data)
        return data

    # -----------------------
    # Case 2: list
    # -----------------------
    if isinstance(data, list):
        return [
            yaml_to_dataclass(f"{name}Item", item)
            for item in data
        ]

    # -----------------------
    # Case 3: dict → dynamic dataclass
    # -----------------------
    fields_list = []
    namespace = {}

    for key, value in data.items():
        child = yaml_to_dataclass(key.capitalize(), value)
        fields_list.append((key, type(child), field(default=None)))
        namespace[key] = child

    # Create dataclass
    cls = make_dataclass(name, fields_list)
    instance = cls()

    # Fill attributes
    for k, v in namespace.items():
        setattr(instance, k, v)

    # Inject getter
    inject_getter(instance)

    return instance

class SwitchConfParser(ConfParser):
    """Parser for switch configuration files in YAML format.

    This class is responsible for loading a switch's configuration based on the hostname,
    validating port settings, and preparing structured port information.
    """

    def __init__(self, conf_path: str):
        """Initializes the SwitchConfParser."""
        super().__init__(conf_path=conf_path)
        self.switches = {}

    def load_conf_file(self):
        """Loads and parses the switch YAML configuration file.


        Raises:
            FileNotFoundError: If the file at `conf_path` does not exist.
            yaml.YAMLError: If YAML parsing fails.
            KeyError: If `hostname` is not found in the switch list.
        """
        try:
            with open(self.conf_path, 'r') as f:
                data = yaml.safe_load(f)
            self.switches = data['switches']
        except FileNotFoundError:
            print("switch config file is not exist: {}".format(self.conf_path))
        except yaml.YAMLError as e:
            print("YAML load error: {}".format(e))
        except KeyError as e:
            print("Missing key in configuration: {}".format(e))

    def _get_switch(self, hostname):
        if hostname not in self.switches:
            raise KeyError("Switch '{}' is not present in {}".format(
                hostname, self.conf_path))
        return self.switches[hostname]

    def _get_required_fields(self, hostname, field_names):
        switch = self._get_switch(hostname)
        missing_fields = [name for name in field_names if name not in switch]
        if missing_fields:
            raise KeyError("Switch '{}' is missing configuration field(s): {}".format(
                hostname, ", ".join(missing_fields)))
        return {name: switch[name] for name in field_names}

    @staticmethod
    def _validate_non_negative_int(hostname, field_name, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("Switch '{}': {} must be an integer".format(
                hostname, field_name))
        if value < 0:
            raise ValueError("Switch '{}': {} must be non-negative".format(
                hostname, field_name))

    def parse_dcqcn_config(self, hostname):
        """Return and validate DCQCN parameters for a switch."""
        config = self._get_required_fields(hostname, (
            'DCQCN_K_MIN', 'DCQCN_K_MAX', 'DCQCN_P_MAX', 'SEED_RANGE_MAX'))

        for field_name in ('DCQCN_K_MIN', 'DCQCN_K_MAX', 'SEED_RANGE_MAX'):
            self._validate_non_negative_int(
                hostname, field_name, config[field_name])

        p_max = config['DCQCN_P_MAX']
        if isinstance(p_max, bool) or not isinstance(p_max, (int, float)):
            raise TypeError("Switch '{}': DCQCN_P_MAX must be a number".format(
                hostname))
        if not 0 <= p_max <= 1:
            raise ValueError("Switch '{}': DCQCN_P_MAX must be between 0 and 1".format(
                hostname))
        if config['DCQCN_K_MIN'] > config['DCQCN_K_MAX']:
            raise ValueError("Switch '{}': DCQCN_K_MIN must not exceed DCQCN_K_MAX".format(
                hostname))

        return config

    def parse_multicast_config(self, hostname):
        """Return and validate multicast parameters for a switch."""
        config = self._get_required_fields(
            hostname, ('MCAST_GRP_ID', 'RID'))
        for field_name, value in config.items():
            self._validate_non_negative_int(hostname, field_name, value)
        return config

    def parse_buffer_config(self, hostname):
        """Return and validate buffer and PFC parameters for a switch."""
        config = self._get_required_fields(hostname, (
            'ingress_buffer_cells', 'egress_buffer_cells',
            'skid_max_cells', 'guaranteed_cells', 'PFC_ENABLE',
            'ingress_dynamic_baf', 'egress_dynamic_baf'))

        for field_name in (
                'ingress_buffer_cells', 'egress_buffer_cells',
                'skid_max_cells', 'guaranteed_cells'):
            self._validate_non_negative_int(
                hostname, field_name, config[field_name])

        if not isinstance(config['PFC_ENABLE'], bool):
            raise TypeError("Switch '{}': PFC_ENABLE must be a boolean".format(
                hostname))

        for field_name in ('ingress_dynamic_baf', 'egress_dynamic_baf'):
            value = config[field_name]
            if not isinstance(value, str) or not value:
                raise TypeError("Switch '{}': {} must be a non-empty string".format(
                    hostname, field_name))

        return config

    def get_fp_port_and_lane(self, fp_port_and_lane):
        match = re.search(r'(\d+)/(\d+)', fp_port_and_lane)
        if match is None:
            raise SyntaxError('Format of Port {} is illegal, must be CONN_ID/CHNL_ID'.format(fp_port_and_lane))
        return int(match.group(1)), int(match.group(2))

    def check_port_format(self, fp_port_and_lane, speed, fec, an):
        """Validates the format and configuration of a front-panel port.

        Args:
            fp_port_and_lane (str): Port string in the format "CONN_ID/CHNL_ID".
            speed (str): Port speed (e.g., "25G", "100G").
            fec (str): FEC type ("none", "fc", "rs").
            an (str): Auto-negotiation setting ("default", "enable", "disable").

        Returns:
            Tuple[Tuple[int, int, int, str, str], int]: A tuple containing:
                - A tuple of port details (conn_id, chnl_id, speed, fec, an).
                - The corresponding dev_port number.

        Raises:
            SyntaxError: If the port string format is invalid or configuration values are not allowed.
        """
        match = re.search(r'(\d+)/(\d+)', fp_port_and_lane)
        if match is None:
            raise SyntaxError('Format of Port {} is illegal, must be CONN_ID/CHNL_ID'.format(fp_port_and_lane))
        else:
            conn_id = int(match.group(1))
            chnl_id = int(match.group(2))

        if speed not in ["10G", "25G", "40G", "50G", "100G"]:
            raise SyntaxError('Port {} speed must be one of 10G, 25G, 40G, 50G, 100G'.format(fp_port_and_lane))
        else:
            match = re.match(r'\d+', speed)
            speed = int(match.group())

        if fec not in ["none", "fc", "rs"]:
            raise SyntaxError('Port {} fec must be one of none, fc, rs'.format(fp_port_and_lane))

        if an not in ["default", "enable", "disable"]:
            raise SyntaxError('Port {} an must be one of default, enable, disable'.format(fp_port_and_lane))

        return (conn_id, chnl_id, speed, fec, an)

    def parse_ports(self, hostname):
        """Parses and validates the loaded port configuration.

        Iterates through the port dictionary and validates each entry.
        If any port fails validation, an error message is printed and None is returned.

        Returns:
            list[Tuple[int, int, int, str, str]] or None: 
                A list of valid port configurations, or None if validation fails.
        """
        port_list = []
        switch = self.switches[hostname]
        ports = switch['ports']
        for (fp_port_and_lane, config) in ports.items():
            try:
                speed = config['speed']
                fec = config['fec']
                an = config['an']
                port_tuple = self.check_port_format(
                    fp_port_and_lane=fp_port_and_lane, speed=speed, fec=fec, an=an)
                port_list.append(port_tuple)

            except SyntaxError as e:
                print('port configure file has format error: {}'.format(e))
                return None

        return port_list

class TopoConfParser(ConfParser):
    """Parses topology configuration files in YAML format.

    This class extends `ConfParser` and is used to parse and store
    topology-related information, including senders, receivers,
    switches, and their connections and links.
    """

    def __init__(self, conf_path: str):
        """Initializes an empty topology configuration."""
        super().__init__(conf_path=conf_path)
        self.senders = {}      
        self.receivers = {}      
        self.switch_nodes = {}     
        self.links = []        

    def load_conf_file(self):
        """Loads and parses a topology YAML configuration file.

        Parses node types (sender, receiver, switch) and populates internal
        dictionaries for senders, receivers, and switches, as well as lists
        for connections and links.


        Raises:
            FileNotFoundError: If the file at `conf_path` does not exist.
            yaml.YAMLError: If the file cannot be parsed as valid YAML.
            KeyError: If expected keys (like 'nodes') are missing in the YAML.
        """
        try:
            with open(self.conf_path, 'r') as f:
                data = yaml.safe_load(f)
            # parse links
            for link in data['links']:
                self.links.append((link['from'], link['port_from'], link['to'], link['port_to']))
            # parse nodes
            self.switch_nodes = data['switch_nodes']
        except FileNotFoundError:
            print("switch config file is not exist: {}".format(self.conf_path))
        except yaml.YAMLError as e:
            print("YAML load error: {}".format(e))
        except KeyError as e:
            print("Missing key in configuration: {}".format(e))
            
class ConnectionConfParser(ConfParser):
    """Parser for connection configuration files in YAML format.

    This class is responsible for loading connection configurations.
    """

    def __init__(self, conf_path: str):
        """Initializes the ConnectionConfParser."""
        super().__init__(conf_path=conf_path)
        self.connections = []
        self.hosts = set()

    def load_conf_file(self):
        """Loads and parses the connection YAML configuration file.

        Args:
            conf_path (str): Path to the YAML configuration file.
        """
        try:
            with open(self.conf_path, 'r') as f:
                data = yaml.safe_load(f)
            for connection in data['connections']:
                self.connections.append({'receiver': connection['receiver'], 'sender': connection['sender']})
                self.hosts.add(connection['receiver'])
                self.hosts.add(connection['sender'])
        except FileNotFoundError:
            print("connection config file is not exist: {}".format(self.conf_path))
        except yaml.YAMLError as e:
            print("YAML load error: {}".format(e))
        except KeyError as e:
            print("Missing key in configuration: {}".format(e))

@dataclass
class TestConfig:
    """Root config dataclass (auto generated, YAML filled)."""
    name: Any = None
    description: Any = None
    log: Any = None
    applications: Any = None
    config: Any = None
    root_path: Any = None
         
class TestConfParser(ConfParser):
    """Parser for test configuration files in YAML format.

    This class is responsible for loading test configurations.
    """
    def __init__(self, conf_path: str):
        """Initializes the TestConfParser."""
        super().__init__(conf_path=conf_path)
        self.conf: TestConfig | None = None

    def load_conf_file(self):
        """Loads and parses the test YAML configuration file.

        Args:
            conf_path (str): Path to the YAML configuration file.
        """
        try:
            with open(self.conf_path, 'r') as f:
                data = yaml.safe_load(f)
            self.conf = yaml_to_dataclass("TestConfig", data)
        except FileNotFoundError:
            print("test config file is not exist: {}".format(self.conf_path))
        except yaml.YAMLError as e:
            print("YAML load error: {}".format(e))
        except KeyError as e:
            print("Missing key in configuration: {}".format(e))
    
    def get(self):
        return self.conf
    
    def get_remote_rdma_cmd_config(self, cmd: str, cmd_config):
        if self.conf is None:
            raise RuntimeError("not run load_conf_file")
        env = Environment()
        ast = env.parse(cmd)
        variables = meta.find_undeclared_variables(ast)
        cmd_config_dict = {}
        for variable in variables:
            cmd_config_dict[variable] = cmd_config.get(variable)
        return cmd_config_dict
    
            
class HostConfParser(ConfParser):
    """Parser for host configuration files in YAML format.

    This class is responsible for loading host configurations.
    """

    def __init__(self, conf_path: str):
        """Initializes the HostConfParser."""
        super().__init__(conf_path=conf_path)
        self.hosts = {}
        self.senders = []
        self.receivers = []

    def load_conf_file(self):
        """Loads and parses the host YAML configuration file.

        Args:
            conf_path (str): Path to the YAML configuration file.
        """
        try:
            with open(self.conf_path, 'r') as f:
                data = yaml.safe_load(f)
            self.hosts = data['hosts']
            self.senders = [host for host, cfg in self.hosts.items() if cfg['type'] == 'sender']
            self.receivers = [host for host, cfg in self.hosts.items() if cfg['type'] == 'receiver']
        except FileNotFoundError:
            print("host config file is not exist: {}".format(self.conf_path))
        except yaml.YAMLError as e:
            print("YAML load error: {}".format(e))
        except KeyError as e:
            print("Missing key in configuration: {}".format(e))
    
    def add_host_info(self, host: str, info: dict):
        self.hosts[host].update(info)
        try:
            with open(self.conf_path, 'w') as f:
                yaml.safe_dump({'hosts': self.hosts}, f)
        except FileNotFoundError:
            print("host config file is not exist: {}".format(self.conf_path))
