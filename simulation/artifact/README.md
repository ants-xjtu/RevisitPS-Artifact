# Simulation Artifact

Run simulation commands from `simulation/`. Simulation runs require the Docker
environment described in the repository-level [README](../../README.md).
Parsing and plotting can run on the host.

## Quick Start

Inspect commands without running experiments:

```bash
./artifact/run_artifact.sh --section all --stage all --dry-run
```

Run, monitor, parse, and plot one section:

```bash
./artifact/run_artifact.sh --section lossless --stage run --run-id trial1
./artifact/run_artifact.sh --section lossless --stage status --run-id trial1
./artifact/run_artifact.sh --section lossless --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossless --stage plot --run-id trial1
```

Run only one workload family:

```bash
./artifact/run_artifact.sh \
  --section lossy \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1
```

Continue an interrupted run or submit only missing and failed tasks:

```bash
./artifact/run_artifact.sh \
  --section lossy \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1 \
  --resume
```

## Options

```text
--section lossless|lossy|asymmetric|all
--workload datacenter-workloads|collective-communication-workloads|all
--stage run|parse|plot|status|all
--run-id ID       result directory name; default is latest
--resume          continue an existing run
--dry-run         print commands without running them
--spine-id ID     Figure 10 spine node; default is 136
```

Use a different run ID for each independent concurrent command. A run can be
parsed only after its status is `completed`.

## Workload Commands

- [Lossless](lossless/README.md)
- [Lossy](lossy/README.md)
- [Asymmetric](asymmetric/README.md)

Each section contains separate README files for datacenter and collective
communication workloads.

## Results

Managed results are stored by run ID:

```text
artifact/results/<section>/<workload-family>/runs/<run-id>/
  status
  status.json
  logs/
  history/all.history
  manifest.csv
  json/
  figures/
  tables/
```

Raw simulator output is stored under `mix/output/`.

## Validation

These checks do not run experiments:

```bash
find artifact -name '*.sh' -type f -exec bash -n {} +
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s artifact/tests -p 'test_*.py' -v
./artifact/run_artifact.sh --section all --stage all --dry-run
```
