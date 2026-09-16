# PacketLB RoCE ns-3 Simulator

This directory contains the ns-3.19 simulator and managed simulation workflow
for the paper artifact. Plotting is provided by the sibling Bazel workspace at
`../plot/`.

## Directory Layout

```text
simulation/
|-- artifact/        # experiment runners, parsers, manifests, and tests
|-- parser/          # raw-output parsers used by the artifact workflow
|-- run.py           # entry point used by simulation runners
|-- scratch/         # ns-3 simulation programs
|-- src/             # RDMA, switch, load-balancing, and transport models
|-- config/          # topology and traffic configuration inputs
`-- mix/output/      # generated raw outputs, ignored by Git
```

## Docker Build

Docker is the supported environment for building and running simulations. From
the repository root:

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

Inside the container:

```bash
./waf configure --build-profile=optimized
./waf
```

The numeric user and group keep bind-mounted outputs writable by the host
account. The detached container remains available while experiments run. Open
another shell with `docker exec -it revisitps-sim bash`, and remove the
container after all required work is complete with `docker rm -f revisitps-sim`.

## Managed Artifact Workflow

Run and parse simulations inside the container from `simulation/`:

```bash
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

Run the plot stage on the host after installing Bazel as described in
[plot/README.md](../plot/README.md):

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --stage plot \
  --run-id trial1
```

The Docker image does not include Bazel, so use separate stages for the
documented Docker/host workflow. Use `--stage all --dry-run` to inspect the
complete command sequence. See [artifact/README.md](artifact/README.md) for all
options, workload selection, output locations, and the paper figure/table map.

## Local Ubuntu Build

For development outside Docker, the simulator has been used in Ubuntu
20.04-based environments. Run the following commands from the repository root:

```bash
sudo apt update
sudo apt install -y build-essential bzip2 git libgtk-3-0 python2 python3 \
  python3-pip gnuplot procps
python3 -m pip install numpy pandas matplotlib cycler seaborn

cd simulation
./waf configure --build-profile=optimized
./waf
```

Host parsing additionally requires writable access to the raw output and
artifact result directories. Docker parsing is recommended for reproducibility.

## Running One Simulation

`run.py` generates traffic, runs the ns-3 program, and writes raw outputs under
`mix/output/<config-id>/`. Its compatibility history is `mix/.history`.

```bash
python3 run.py --help
```

The `autorun*.sh` scripts support ad hoc sweeps. Use the managed workflow under
`artifact/` when reproducing paper results.

## Validation

These checks do not run experiments:

```bash
find artifact -name '*.sh' -type f -exec bash -n {} \;
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s artifact/tests -p 'test_*.py' -v
./artifact/run_artifact.sh --section all --stage all --dry-run
```

## Simulator Structure

Most load-balancing and RDMA behavior is under
`src/point-to-point/model/`:

- `switch-node.*`: switch forwarding and load-balancing logic.
- `switch-mmu.*`: ingress/egress admission control and PFC behavior.
- `conweave-routing.*`: ConWeave routing support.
- `rdma-hw.*`: RDMA NIC behavior.
- `rdma-queue-pair.*`: queue-pair state and retransmission behavior.
- `settings.*`: shared simulation settings and tracing switches.

## Credits

This codebase is based on the ConWeave ns-3 simulator and the RDMA models from
Alibaba HPCC and ns3-tlt-rdma-public. Keep the original `LICENSE` file with
redistributed copies.
