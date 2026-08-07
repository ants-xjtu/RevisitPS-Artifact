import subprocess
import shlex
from jinja2 import Template, Environment, meta

class RemoteTofinoHelper(object):
  def __init__(self, remote_user, switch_hostname, remote_cwd, arch):
    self.arch = arch
    self.remote_user = remote_user
    self.switch_hostname = switch_hostname
    self.remote_cwd = remote_cwd
    self.envs = []

  def __tmux_new_session(self, session_name):
    tmux_new_session_cmd = f'tmux new-session -d -s {session_name}'
    subprocess.run(tmux_new_session_cmd, shell=True)
    
  def __tmux_send_keys(self, session_name, cmd):
    tmux_send_keys_cmd = f'tmux send-keys -t {session_name} \"{cmd}\" C-m'
    print(tmux_send_keys_cmd)
    subprocess.run(tmux_send_keys_cmd, shell=True)
  
  def __tmux_kill_session(self, session_name):
    tmux_kill_session_cmd = f'tmux kill-session -t {session_name}'
    subprocess.run(tmux_kill_session_cmd, shell=True)
  
  def __correct_p4_pipe_conf(self, remote_cwd, program):
    cd_cmd = f'cd {remote_cwd}'
    correct_p4_pipe_conf_cmd = f'ssh {self.remote_user}@{self.switch_hostname} \"{cd_cmd} && python3 correct_pipe.py --p4_name={program} --arch={self.arch}\"'
    subprocess.run(correct_p4_pipe_conf_cmd, shell=True)

  def __render_remote_cmd(self, cmd, config):
    template = Template(cmd)
    rendered_cmd = template.render(config)
    return rendered_cmd
    
  def sync_repo(self, repo_path, exclude_paths):
    exclude_str = ' '.join([f"--exclude=\'{path}\'" for path in exclude_paths])
    rsync_cmd = f'rsync -avz -e ssh {exclude_str} {repo_path}/ {self.remote_user}@{self.switch_hostname}:{self.remote_cwd}/'
    print(rsync_cmd)
    subprocess.run(rsync_cmd, check=True, cwd=repo_path, shell=True)
  
  def remote_build(self, build_cmd, p4program_path):
    # TODO: hardcode p4_program_path in build_cmd for now
    config = {"p4program_path": p4program_path}
    render_build_cmd = self.__render_remote_cmd(build_cmd, config)
    ssh_build_cmd = f'ssh {self.remote_user}@{self.switch_hostname} \"cd {self.remote_cwd} && {render_build_cmd}\"'
    print(ssh_build_cmd)
    subprocess.run(ssh_build_cmd, shell=True)
    
  def remote_deploy(self, deploy_cmd, p4program_name):
    # kill firstly
    ssh_kill_bfswitchd_cmd = f'ssh {self.remote_user}@{self.switch_hostname} \"sudo pkill -3 bf_switch\"'
    subprocess.run(ssh_kill_bfswitchd_cmd, shell=True)
    # then run bf_switchd in tmux session
    # TODO: hardcode p4_program_name in deploy_cmd for now
    config = {"p4program_name": p4program_name}
    render_deploy_cmd = self.__render_remote_cmd(deploy_cmd, config)
    ssh_run_cmd = f'ssh -t {self.remote_user}@{self.switch_hostname} \\\"{render_deploy_cmd}\\\"'
    print(ssh_run_cmd)
    self.__tmux_kill_session(self.switch_hostname)
    self.__tmux_new_session(self.switch_hostname)
    self.__tmux_send_keys(self.switch_hostname, ssh_run_cmd)
    
  def remote_config(self, config_cmd, cp_script_path, port, topo, switches, hosts):
    remote_wait_cmd = (
      f'cd {shlex.quote(self.remote_cwd)} && '
      f'bash scripts/remote_tofino/wait_port.sh --port={int(port)}'
    )
    subprocess.run(
      ['ssh', f'{self.remote_user}@{self.switch_hostname}', remote_wait_cmd],
      check=True,
    )
    # TODO: hardcode other params in config_cmd for now
    config = {"cp_script_path": cp_script_path, "hostname": self.switch_hostname, "topo": topo, "switches": switches, "hosts": hosts}
    render_config_cmd = self.__render_remote_cmd(config_cmd, config)
    ssh_config_cmd = f'ssh {self.remote_user}@{self.switch_hostname} \"cd {self.remote_cwd} && {render_config_cmd}\"'
    print(ssh_config_cmd)
    subprocess.run(ssh_config_cmd, shell=True)
