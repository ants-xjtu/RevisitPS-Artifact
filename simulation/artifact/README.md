# Simulation Artifact Workflow

Run all commands in this document from `simulation/`.

- Run simulations in the Docker environment described in the repository
  [README](../../README.md).
- Parse completed runs in Docker. Host parsing is also supported when the
  Python dependencies are installed and all input/output paths are writable.
- Plot on the host after installing Bazel as described in
  [plot/README.md](../../plot/README.md).

## Typical Workflow

Inside Docker, run one section, inspect its status, and parse it after all
selected tasks complete:

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

On the host, render the parsed results:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --stage plot \
  --run-id trial1
```

Select only one workload family when needed:

```bash
./artifact/run_artifact.sh \
  --section lossy \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1
```

Continue an interrupted run, or submit only failed and missing tasks:

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

Always specify a meaningful `run-id` to identify the results of each run. Use a
different ID for each independent concurrent command. Reusing an ID for the run stage
requires `--resume`. Datacenter and collective-communication families execute
sequentially within one command; separate commands with different run IDs can
execute concurrently.

The combined `--stage all` mode runs all stages in one environment. Because the
provided simulation image does not include Bazel, use separate `run`, `parse`,
and host-side `plot` commands for normal reproduction. It remains useful with
`--dry-run` to inspect all generated commands.

## Paper Outputs

| Section | Workload family | Paper outputs |
| --- | --- | --- |
| Lossless | Datacenter | Figures 4, 5, 6, and 9; Tables 4 and 5 |
| Lossless | Collective communication | Figures 7, 8, and 10 |
| Lossy | Datacenter | Figures 11 and 12; Tables 6 and 7 |
| Lossy | Collective communication | Figure 13 |
| Asymmetric | Datacenter | Figures 14, 15, and 16; Table 8 |
| Asymmetric | Collective communication | Figure 17 |

Workload-specific command references:

- [Lossless](lossless/README.md)
- [Lossy](lossy/README.md)
- [Asymmetric](asymmetric/README.md)

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

Raw simulator output is stored under `mix/output/<config-id>/`. The manifest
associates each configuration with its paper outputs, while `status.json`
records pending, running, completed, and failed tasks.

## Validation

These checks do not run experiments:

```bash
find artifact -name '*.sh' -type f -exec bash -n {} \;
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s artifact/tests -p 'test_*.py' -v
./artifact/run_artifact.sh --section all --stage all --dry-run
```
