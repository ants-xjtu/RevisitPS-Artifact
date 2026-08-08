# RevisitPS Artifact

This artifact accompanies the paper `Revisiting Network Support for Packet-level Load-balancing in RoCE`. The paper PDF is a local reference copy and is not tracked in this repository. It combines the simulation artifact, testbed automation, and Bazel plotting workspace in a single top-level repository.

## Repository Layout

```text
RevisitPS-Artifact/
|-- simulation/   # ns-3.19 simulator and managed paper artifact workflow
|-- plot/         # Bazel plotting workspace used by simulation/artifact
`-- testbed/      # Tofino and RDMA testbed automation
```

## Component Sources

- `simulation/` was imported from `git@github.com:majinchao2002/load-balance.git`, branch `ai-workload-fixes`, commit `74d5b92`.
- `plot/` was imported from `git@github.com:majinchao2002/monorepo.git`, branch `plb`, commit `86e6371`.
- Nested component `.git` directories are intentionally removed so this artifact behaves as one repository.

## Quick Start

Read the component README files first:

```bash
less simulation/README.md
less simulation/artifact/README.md
less plot/README.md
less testbed/README.md
```

This packaged artifact uses `simulation/` and `plot/` consistently for simulator and plotting paths.

## Simulation Docker

From the artifact root:

```bash
docker build -t revisitps-sim:artifact -f simulation/Dockerfile simulation
docker run --rm -it -v "$(pwd)":/artifact -w /artifact/simulation revisitps-sim:artifact bash
```

Inside the container:

```bash
./waf configure --build-profile=optimized
./waf
```

Use `simulation/artifact/run_artifact.sh --dry-run` to inspect managed artifact commands without running experiments.

## Managed Simulation Artifact

The managed workflow lives under `simulation/artifact/`:

```bash
cd simulation
./artifact/run_artifact.sh --section all --stage all --dry-run
./artifact/run_artifact.sh --section lossless --stage all --run-id trial1
./artifact/run_artifact.sh --section lossy --stage parse --run-id trial1
./artifact/run_artifact.sh --section asymmetric --stage plot --run-id trial1
```

Supported sections are `lossless`, `lossy`, `asymmetric`, and `all`. Supported stages are `run`, `parse`, `plot`, and `all`. Plot stages call Bazel targets under the sibling `plot/` workspace.

## Testbed

The testbed component is under `testbed/`. It requires SSH access to servers and switches, passwordless sudo on servers, and the appropriate Tofino SDE environment on the switch. See `testbed/README.md`.

## Generated Outputs

Generated build products, logs, traces, simulation results, parser outputs, figures, and Bazel outputs are ignored by the top-level `.gitignore`. Key locations are:

- `simulation/mix/output/`: raw ns-3 run outputs.
- `simulation/artifact/results/`: managed artifact histories, JSON, tables, and figures.
- `simulation/logs/`: simulator batch logs.
- `plot/bazel-*`: Bazel symlinks and outputs.
- `testbed/logs/`, `testbed/data/`, `testbed/trace/`: testbed runtime outputs.
