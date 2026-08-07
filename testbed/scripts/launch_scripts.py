import click
import os
from remote_tofino.config_sw import sw, sw_build, sw_run, sw_config
from remote_rdma.check_link import check_one_link, check_all_links
from remote_rdma.run_test import sequential_start, concurrent_start
from common.repo_helper import get_repo_root, get_test_conf_path
from conf_parser.yaml_parser import TestConfParser
from plot.plot_throughput import plot_throughput
from plot.analysis_fct import analysis_fct
from trace.gen_trace import gen_trace_from_host, gen_trace_from_connection
from trace.sync_trace import sync_trace

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
@click.pass_context
def main(ctx, cmd):
  # Anchor every local relative path to the repository root.
  os.chdir(get_repo_root())
  # load test config
  test_conf_path = get_test_conf_path()
  test_conf_parser = TestConfParser(test_conf_path)
  test_conf_parser.load_conf_file()
  # mkdir for runtime logs
  test_conf = test_conf_parser.get()
  runtime_log_dir = test_conf.log.dir
  os.makedirs(runtime_log_dir, exist_ok=True)
  # invoke command
  ctx.invoke(CMD_MAP[cmd], test_conf_parser=test_conf_parser)

if __name__ == "__main__":
  main()
