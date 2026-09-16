# Testbed Artifact

This directory contains the Tofino and RDMA testbed automation used by the
artifact: P4 programs, switch control-plane scripts, RDMA traffic scripts,
experiment configurations, and analysis helpers.

Testbed execution is hardware- and site-specific. The checked-in YAML files
contain deployment assumptions such as host names, interfaces, switch ports,
remote paths, and SDE commands. Review and adapt them to the target deployment
before running any command that controls hardware or starts traffic.

## Requirements

- SSH key access to every configured server and switch.
- Passwordless `sudo` on the configured servers.
- A compatible Tofino switch and SDE environment.
- RDMA interfaces and tools matching the selected YAML configuration.
- Python 3 on the orchestration host.

Run commands from `testbed/` unless stated otherwise.

## Python Environment

From the repository root:

```bash
cd testbed
python3 -m venv testbed-venv
source testbed-venv/bin/activate
python3 -m pip install -r requirements.txt
make env
```

`make env` writes `.env` with the artifact-local `PYTHONPATH` required by
`testbed/utils`.

## Configuration

Choose a YAML file under `conf/test/` and export it before using a Make target:

```bash
export TEST_CONF_PATH=conf/test/ecmp-8-client-8-server-WebSearch-lossless-80%.yaml
```

Review the referenced host, switch, topology, connection, and trace files
before execution. The local `root_path: .` is anchored to `testbed/`. Remote
Tofino configurations commonly use `cwd: testbed`, which is the component's
working directory after it is synchronized to the switch.

## Switch and Traffic Commands

These targets access testbed hardware:

```bash
make sw_build
make sw_run
make sw_config
make check_one_link
make check_all_links
make sequential_start
make concurrent_start
```

`make sw` combines switch build, run, and configuration. The exact remote
effects are determined by `TEST_CONF_PATH` and its referenced YAML files.

## Trace and Analysis Commands

```bash
make gen_trace_from_host
make gen_trace_from_connection
make sync_trace
make plot_throughput
make analysis_fct
```

Trace generation and analysis operate on the paths selected by the deployment
configuration. `sync_trace` performs remote synchronization and therefore also
requires configured SSH access.

## Directory Layout

- `conf/`: host, switch, topology, connection, trace, and experiment YAML.
- `scripts/`: launchers, RDMA and Tofino helpers, trace generation, and plots.
- `src/`: P4 data-plane programs and control-plane code.
- `utils/`: configuration, BFRT, path, and remote-execution helpers.
- `Makefile`: command-line entry points.
