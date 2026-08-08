# Testbed Artifact

This directory contains Tofino and RDMA testbed automation for the artifact. It includes P4 data-plane programs, control-plane scripts, RDMA traffic scripts, experiment configurations, and testbed plotting helpers.

## Prepare

- Ensure every server and switch can be accessed via SSH using key-based authentication.
- Ensure every server has passwordless sudo privileges.
- Ensure the Tofino switch has the required SDE environment commands, such as `sde-env-9.9.1`.
- Run testbed commands from `testbed/` unless a command explicitly says otherwise.

## Python Environment

```bash
cd testbed
python3 -m venv testbed-venv
source testbed-venv/bin/activate
python3 -m pip install -r requirements.txt
make env
```

`make env` writes `.env` with the correct artifact-local `PYTHONPATH` for `testbed/utils`.

## Usage

Set `TEST_CONF_PATH` to one of the YAML files under `conf/test/`, then run a make target:

```bash
cd testbed
source testbed-venv/bin/activate
make env
export TEST_CONF_PATH=conf/test/ecmp-8-client-8-server-WebSearch-lossless-80%.yaml
make sw_build
```

Common targets:

- `make sw`: build, run, and configure the Tofino switch program.
- `make sw_build`: compile the P4 program.
- `make sw_run`: run `bf_switchd` on the Tofino switch.
- `make sw_config`: run the control-plane configuration script.
- `make check_one_link` / `make check_all_links`: run RDMA link checks.
- `make sequential_start` / `make concurrent_start`: run RDMA tests.
- `make gen_trace_from_host` / `make gen_trace_from_connection`: generate traffic traces.
- `make sync_trace`: sync generated traces.
- `make plot_throughput` / `make analysis_fct`: analyze testbed results.

## Structure

- `conf/`: host, switch, topology, connection, trace, and experiment YAML files.
- `scripts/`: launch scripts, remote RDMA helpers, remote Tofino helpers, trace generation, and plotting utilities.
- `src/`: P4 data-plane programs and control-plane code.
- `utils/`: common libraries for config parsing, BFRT helpers, repository path handling, and remote execution.
- `Makefile`: common command-line entry points.

## Path Notes

The launcher anchors local paths to the `testbed/` directory through `utils/common/repo_helper.py`. The YAML field `root_path: .` therefore means `testbed/`, not the artifact root. Remote Tofino configs commonly use `cwd: testbed`, which is the remote working directory after syncing this component to the switch.
