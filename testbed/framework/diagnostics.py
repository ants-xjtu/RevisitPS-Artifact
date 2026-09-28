import click
import os
from switches.scripts.config_sw import sw, sw_build, sw_run, sw_config
from framework.rdma.check_link import check_one_link, check_all_links
from framework.rdma.run_test import sequential_start, concurrent_start
from framework.paths import get_repo_root, get_test_conf_path
from framework.conf_parser.yaml_parser import TestConfParser
from experiments.dcn_workload.scripts.plot_throughput import plot_throughput
from experiments.dcn_workload.scripts.parse import analysis_fct
from experiments.dcn_workload.scripts.generate_trace import gen_trace_from_host, gen_trace_from_connection
from experiments.dcn_workload.scripts.sync_trace import sync_trace

CMD_MAP = {
  "sw": sw,
  "sw_build": sw_build,
  "sw_run": sw_run,
  "sw_config": sw_config,
  "check_one_link": check_one_link,
  "check_all_links": check_all_links,
  "sequential_start": sequential_start,
  "concurrent_start": concurrent_start,
  "plot_throughput": plot_throughput,
  "gen_trace": gen_trace_from_host,
  "gen_trace_from_host": gen_trace_from_host,
  "gen_trace_from_connection": gen_trace_from_connection,
  "sync_trace": sync_trace,
  "analysis_fct": analysis_fct
}

@click.command()
@click.option("--cmd", type=click.Choice(CMD_MAP.keys()))
@click.option('--config', 'config_path', type=click.Path(exists=True), default=None,
              help='Runtime YAML produced by artifact preparation')
@click.option('--src', default=None)
@click.option('--dst', default=None)
@click.pass_context
def main(ctx, cmd, config_path, src, dst):
  # Anchor every local relative path to the repository root.
  os.chdir(get_repo_root())
  # load test config
  test_conf_path = config_path or get_test_conf_path()
  if not test_conf_path:
    raise click.UsageError('--config or TEST_CONF_PATH is required')
  test_conf_parser = TestConfParser(test_conf_path)
  test_conf_parser.load_conf_file()
  # mkdir for runtime logs
  test_conf = test_conf_parser.get()
  runtime_log_dir = test_conf.log.dir
  os.makedirs(runtime_log_dir, exist_ok=True)
  # invoke command
  kwargs = {'test_conf_parser': test_conf_parser}
  if cmd == 'check_one_link':
    if not src or not dst:
      raise click.UsageError('check_one_link requires --src and --dst')
    kwargs.update(src=src, dst=dst)
  ctx.invoke(CMD_MAP[cmd], **kwargs)

if __name__ == "__main__":
  main()
