# PacketLB RoCE ns-3 Artifact

This directory contains the ns-3.19 simulator used for the paper artifact in `../nsdi27spring-paper67.pdf`. It extends the ConWeave/RDMA ns-3 codebase with experiments for packet-level load balancing, lossy/lossless RoCE behavior, collective-communication workloads, and asymmetric topologies.

The managed artifact workflow is under `artifact/`. Plotting is done by the sibling Bazel workspace at `../plot`.

## Packaged Repository Layout

```text
RevisitPS-Artifact/
|-- simulation/
|   |-- artifact/        # paper artifact orchestration, parsers, manifests, tests
|   |-- parser/          # raw-output parsers used by artifact wrappers
|   |-- run.py           # single simulation entry point used by all runners
|   |-- scratch/         # ns-3 simulation programs
|   |-- src/             # RDMA, switch, load-balancing, and transport model code
|   |-- config/          # topology and generated traffic configuration inputs
|   `-- mix/output/      # raw simulation outputs, ignored by Git
`-- plot/                # Bazel plotting workspace
```

## Docker Quick Start

From the artifact root:

```bash
docker build -t revisitps-sim:artifact -f simulation/Dockerfile simulation
docker run --rm -it -v "$(pwd)":/artifact -w /artifact/simulation revisitps-sim:artifact bash
```

Build ns-3 inside the container:

```bash
./waf configure --build-profile=optimized
./waf
```

For a detached container:

```bash
docker run -dit --name revisitps-sim -v "$(pwd)":/artifact -w /artifact/simulation revisitps-sim:artifact bash
docker exec -it revisitps-sim bash
docker rm -f revisitps-sim
```

## Local Ubuntu Build

The simulator has been used on Ubuntu 20.04-style environments. Newer Ubuntu versions usually work if the same packages are available.

```bash
sudo apt update
sudo apt install -y build-essential bzip2 git libgtk-3-0 python2 python3 python3-pip gnuplot procps
python3 -m pip install numpy pandas matplotlib cycler seaborn

cd simulation
./waf configure --build-profile=optimized
./waf
```

## Running One Simulation

`run.py` generates traffic, launches the ns-3 program, and writes raw outputs under `mix/output/<config-id>/`. The run history is recorded in `mix/.history`.

```bash
python3 run.py --help
```

The legacy `autorun*.sh` scripts are kept for ad-hoc sweeps. For the paper artifact, use the managed scripts under `artifact/` instead.

## Paper Artifact Workflow

Run from `simulation/`:

```bash
./artifact/run_artifact.sh --section all --stage all --dry-run
./artifact/run_artifact.sh --section lossless --stage all --run-id trial1
./artifact/run_artifact.sh --section lossless --workload datacenter-workloads --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossless --stage status --run-id trial1
./artifact/run_artifact.sh --section lossy --stage parse --run-id trial1
./artifact/run_artifact.sh --section asymmetric --stage plot --run-id trial1
```

Supported sections are `lossless`, `lossy`, `asymmetric`, and `all`. Use
`--workload datacenter-workloads|collective-communication-workloads|all` to
select one workload family. Supported stages are `run`, `parse`, `plot`,
`status`, and `all`.
Within each selected section, datacenter and collective-communication workload
families run sequentially. A failed family does not skip the remaining family;
the command returns nonzero after all selected families have been attempted.


Managed outputs are stored under:

```text
artifact/results/<section>/<workload-family>/runs/<run-id>/
  status
  status.json
  logs/
  history/all.history
  manifest.csv
  json/<semantic-output>/
  figures/
  tables/
```

Generated outputs are ignored by Git. Lossless managed runs append each history row to both the compatibility log `mix/.history` and the selected `run-id` as soon as the simulation is configured. At the same time, `manifest.csv` receives the `config_id` and its `paper_outputs` marker. `status.json` tracks pending, running, completed, and failed tasks. Different run IDs can run concurrently; reusing the same run ID is rejected. Raw simulator output remains in `mix/output/<config-id>/`.

Run the simulation stage inside Docker. The parse stage reads existing raw
outputs and the plot stage uses the sibling Bazel workspace, so both can run on
the host. Figure-specific selected histories, legacy parser workspaces, and
plot intermediates use temporary directories and are removed automatically;
managed `json/` directories are not used as plotting workspaces.

See `artifact/README.md` for the paper figure/table map and `../plot/README.md` for Bazel plotting setup.

## Validation

These commands do not run experiments:

```bash
find artifact -name '*.sh' -type f -exec bash -n {} +
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s artifact/tests -p 'test_*.py' -v
./artifact/run_artifact.sh --section all --stage all --dry-run
```

## Simulator Structure

Most load-balancing and RDMA behavior is implemented under `src/point-to-point/model/`.

- `switch-node.*`: switch forwarding and load-balancing logic.
- `switch-mmu.*`: ingress/egress admission control and PFC behavior.
- `conweave-routing.*`: ConWeave routing support.
- `rdma-hw.*`: RDMA NIC behavior.
- `rdma-queue-pair.*`: queue-pair state and retransmission behavior.
- `settings.*`: global simulation settings and tracing switches.

## Credits

This codebase is based on the ConWeave ns-3 simulator and the RDMA models from Alibaba HPCC and ns3-tlt-rdma-public. Keep the original `LICENSE` file with redistributed copies.
