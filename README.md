# RevisitPS Artifact

This repository contains the artifact for *Revisiting Network Support for
Packet-level Load-balancing in RoCE*. It packages the simulator, the plotting
code, and the testbed automation in one repository.

## Repository Layout

```text
RevisitPS-Artifact/
|-- simulation/   # ns-3.19 simulator and managed experiment workflow
|-- plot/         # Bazel workspace for paper figures
`-- testbed/      # Tofino and RDMA testbed automation
```

## Prerequisites

- Docker for building and running the simulator.
- Bazelisk or Bazel 6.5.0 for plotting on the host.
- Sufficient CPU, memory, and disk space for the selected simulation section.

The testbed artifact has additional hardware and deployment requirements; see
[testbed/README.md](testbed/README.md).

## Simulation Quick Start

From the repository root, build the image and create a detached container:

```bash
docker build -t revisitps-sim:artifact -f simulation/Dockerfile simulation
docker run -dit --name revisitps-sim \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  -v "$(pwd)":/artifact \
  -w /artifact/simulation \
  revisitps-sim:artifact bash
docker exec -it revisitps-sim bash
```

Inside the container, build the simulator, run one section, monitor it, and
parse the completed results:

```bash
./waf configure --build-profile=optimized
./waf

./artifact/run_artifact.sh \
  --section lossless \
  --stage run \
  --run-id trial1

./artifact/run_artifact.sh \
  --section lossless \
  --stage status \
  --run-id trial1

./artifact/run_artifact.sh \
  --section lossless \
  --stage parse \
  --run-id trial1
```

The `--user` setting keeps files in the bind mount owned by the host account.
The `run` command waits until all selected experiment groups finish. Open a
second terminal and use `docker exec -it revisitps-sim bash` to inspect status
while it is running. To continue an interrupted run or rerun only failed and
missing tasks, add `--resume` to the original `run` command.

Parsing may also run on a host with the documented Python dependencies, as long
as the raw and result directories are writable. Running it in the container is
the supported default and avoids bind-mount ownership differences.

## Plotting Results

The simulation image does not include Bazel. Install Bazelisk as described in
[plot/README.md](plot/README.md), then run the plot stage on the host:

```bash
cd plot
bazel build //main/plot_artifact/... //main/plot_sample:all

cd ../simulation
./artifact/run_artifact.sh \
  --section lossless \
  --stage plot \
  --run-id trial1
```

Use `--section lossy` or `--section asymmetric` for the other paper sections.
Use `--workload datacenter-workloads` or
`--workload collective-communication-workloads` to select one workload family.
Detailed commands, result paths, and the paper output map are in
[simulation/artifact/README.md](simulation/artifact/README.md).

From the repository root, inspect the complete managed command set without
running experiments:

```bash
cd simulation
./artifact/run_artifact.sh --section all --stage all --dry-run
```

## Generated Outputs

Generated files are ignored by Git. The main locations are:

- `simulation/mix/output/`: raw ns-3 outputs.
- `simulation/artifact/results/`: run status, logs, histories, parsed data,
  tables, and figures.
- `simulation/logs/`: simulator batch logs.
- `plot/bazel-*`: Bazel outputs and convenience symlinks.
- `testbed/logs/`, `testbed/data/`, and `testbed/trace/`: testbed outputs.

Use a distinct `run-id` for each independent or concurrent invocation. The ID
keeps status, metadata, parsed data, and paper outputs associated with the same
run.
