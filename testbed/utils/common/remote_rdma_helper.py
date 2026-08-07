import subprocess
import ipaddress
import re
import os
from conf_parser.yaml_parser import HostConfParser
from jinja2 import Template, Environment, meta

class RemoteRDMAHelper(object):
  COUNTER_COMMAND_TEMPLATE = """
    echo "===== {hostname} ({nic}) @ {pci} ====="
    date
    echo
    echo "--- Ethtool counters ---"
    IFACE=$(ls /sys/class/infiniband/{nic}/device/net/ 2>/dev/null | head -n 1)
    if [ -n "$IFACE" ]; then
        echo "Found network interface: $IFACE. Collecting ethtool stats..."
        ethtool -S $IFACE
    else
        echo "WARNING: Could not find network interface for {nic}."
    fi
    echo
    echo "--- RDMA counters ---"
    COUNTER_DIR="/sys/class/infiniband/{nic}/ports/1/counters"
    if [ -d "$COUNTER_DIR" ]; then
        for f in $COUNTER_DIR/*; do
            printf "%-35s %s\\n" "$(basename $f):" "$(cat "$f" 2>/dev/null || echo 'read_error')"
        done
    else
        echo "ERROR: RDMA counter directory not found: $COUNTER_DIR"
    fi
  """
  def __init__(self, remote_user, hostname, interface, ip):
    self.remote_user = remote_user
    self.hostname = hostname
    self.interface = interface
    self.ip = ip
    self.mlx_device_name = None
    self.bus_info = None
    self.gid = None
    
  
  def __fill_info_file(self, host_conf_parser: HostConfParser):
    host_info = {
      'mlx_device_name': self.mlx_device_name,
      'bus_info': self.bus_info,
      'gid': self.gid
    }
    host_conf_parser.add_host_info(self.ip, host_info)
    
  
  
  def __get_gid_by_ip(self):
        cmd = f"ibv_devinfo -d {self.mlx_device_name} -v | grep -F 'GID['"
        try:
            output = subprocess.check_output(
                ["ssh", f"{self.remote_user}@{self.hostname}", cmd],
                stderr=subprocess.STDOUT
            )
            decoded = output.decode("utf-8").strip().splitlines()
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] 执行远端 ibv_devinfo 失败: {e.output.decode()}")
            return None

        for line in decoded:
            parts = line.strip().split()
            if len(parts) < 2:
                continue

            index_str2 = parts[1]
            gid_value = parts[2]

            if gid_value == f'::ffff:{self.ip},':
                index = int(index_str2.split("]")[0])
                self.gid = index
                return self.gid

        print(f"[WARN] 没有找到 IP {self.ip} 对应的 GID")
        return None
  
  def __get_mlx_device_name(self):
    output = subprocess.check_output(['ssh', f'{self.remote_user}@{self.hostname}', '\'ibdev2netdev\''])
    format_output = output.decode('utf-8')
    lines = format_output.strip().split('\n')
    for line in lines:
      match = re.match(r'(mlx\d+_\d+).*==>\s+(\S+)', line)
      if match and match.lastindex == 2:
        if self.interface == match.group(2):
          self.mlx_device_name = match.group(1)
      else:
        raise RuntimeError('ibdev2netdev output is illegal')
    print(self.mlx_device_name)
    if self.mlx_device_name is None:
      raise RuntimeError(f'no mlx device in {self.hostname}')
  
  def __get_bus_info(self):
    cmd = f"ethtool -i {self.interface} | awk '/bus-info:/ {{print $2}}'"
    output = subprocess.check_output(['ssh', f'{self.remote_user}@{self.hostname}', cmd])
    format_output = output.decode('utf-8')
    self.bus_info = format_output.rstrip()
    
  def __check_remote_port(self, port_to_check):
    try:
        cmd = [
            "ssh",
            f"{self.remote_user}@{self.hostname}",
            f"ss -ltnp | grep :{port_to_check} || true"
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0 and not result.stdout.strip():
            print(f"[error] SSH cmd failed: {result.stderr.strip()}")
            return None

        output = result.stdout.strip()
        if output:
            return True
        else:
            return False

    except subprocess.TimeoutExpired:
        print(f"[error] SSH connection {self.hostname} timeout")
        return None
    except Exception as e:
        print(f"[error] check failed: {e}")
        return None
      
  def __check_remote_cmd(self, cmd, config):
    env = Environment()
    ast = env.parse(cmd)
    variables = meta.find_undeclared_variables(ast)
    missing_vars = [var for var in variables if var not in config]
    if missing_vars:
      raise RuntimeError(f"Missing variables in remote command config: {missing_vars}")

  def __render_remote_cmd(self, cmd, config):
    template = Template(cmd)
    rendered_cmd = template.render(config)
    return rendered_cmd

  def get_mellanox_info(self, host_conf_parser: HostConfParser):
    try:
      host_info = host_conf_parser.hosts[self.ip]
      self.mlx_device_name = host_info['mlx_device_name']
      self.bus_info = host_info['bus_info']
      self.gid = host_info['gid']
    except KeyError:
      self.__get_mlx_device_name()
      self.__get_bus_info()
      self.__get_gid_by_ip()
      self.__fill_info_file(host_conf_parser=host_conf_parser)
  
  def config_mlxreg(self, reg_name, option_table):
    config_reg_accl_cmd = f'sudo mlxreg -d {self.bus_info} --reg_name {reg_name} -y --set '
    options = [f'{option}={int(enable)}' for option, enable in option_table.items()]
    option_cmd = ",".join(options)
    config_reg_accl_cmd = config_reg_accl_cmd + option_cmd
    ssh_cmd = f'ssh {self.remote_user}@{self.hostname} {config_reg_accl_cmd}'
    subprocess.run(ssh_cmd, shell=True)

  def run_command(self, cmd: str, config: dict, timeout: int, log_path: str, is_receiver: bool = False):
    if self.mlx_device_name is None or self.gid is None:
      raise RuntimeError("Mellanox device info is not initialized.")
    # prepare config
    config['mlx_device_name'] = self.mlx_device_name
    config['gid'] = self.gid
    config['log_path'] = log_path
    # check cmd
    self.__check_remote_cmd(cmd, config)
    # render command template
    run_cmd = self.__render_remote_cmd(cmd, config)
    ssh_cmd = f'ssh {self.remote_user}@{self.hostname} \"{run_cmd}\"'
    print(f"{self.ip} run:{ssh_cmd}")
    # run command
    proc = subprocess.Popen(ssh_cmd, shell=True)
    if is_receiver is False:
      try:
        return_code = proc.wait(timeout=timeout)
        print(f"client {self.ip} finished with return code: {return_code}")
      except subprocess.TimeoutExpired:
        print(f"client {self.ip} timeout, killing process...")        
      
  def stop_command(self, kill_cmd):
    ssh_cmd = f'ssh {self.remote_user}@{self.hostname} \'{kill_cmd}\''
    print(f"echo {ssh_cmd}")
    subprocess.run(ssh_cmd, shell=True)
    
  def sync_local_to_remote(self, local_path, remote_path):
    run_cmd = f'scp -r {local_path} {self.remote_user}@{self.hostname}:{remote_path}'
    subprocess.run(run_cmd, shell=True)
  
  def sync_remote_to_local(self, remote_path, local_path):
    run_cmd = f'scp -r {self.remote_user}@{self.hostname}:{remote_path} {local_path}'
    subprocess.run(run_cmd, shell=True)
    
  def get_counter(self):
    cmd = self.COUNTER_COMMAND_TEMPLATE.format(hostname=self.hostname, nic=self.mlx_device_name, pci=self.bus_info)
    ssh_cmd = f'ssh {self.remote_user}@{self.hostname} \'{cmd}\''
    try:
      output = subprocess.check_output(ssh_cmd, shell=True, stderr=subprocess.STDOUT, timeout=20)
      decoded = output.decode('utf-8')
      return decoded
    except subprocess.CalledProcessError as e:
      print(f"[ERROR] 获取远端 RDMA 计数器失败: {e.output.decode()}")
      return f"ERROR: Failed to get counters from {self.hostname}"
    
def sync_log_local(remote_path, target_path):
  run_cmd = f'cp {remote_path} {target_path}'
  subprocess.run(run_cmd, shell=True)
  
def generate_ip_helper_map(ip_list: list, info: dict, remote_user: str):
  ip_rdma_helper_map = {}
  for ip in ip_list:
    ip_rdma_helper_map[ip] = RemoteRDMAHelper(
      remote_user=remote_user,
      hostname=info[ip]['hostname'],
      interface=info[ip]['eth'],
      ip=ip
    )
  return ip_rdma_helper_map
      