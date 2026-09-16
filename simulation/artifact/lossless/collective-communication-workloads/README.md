# Lossless Collective-Communication Workloads

Run commands from `simulation/`. Inside Docker, start the workload:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1
```

Inspect status or continue an interrupted run:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage status \
  --run-id trial1

./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1 \
  --resume
```

After the run completes, parse it inside Docker:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage parse \
  --run-id trial1
```

The lossless datacenter results with the same run ID must be available when
parsing Figure 8. Then render the figures on the host with Bazel installed:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage plot \
  --run-id trial1
```

Add `--spine-id ID` to the plot command only when selecting a different Figure
10 spine. Results are stored under
`artifact/results/lossless/collective-communication-workloads/runs/trial1/`.
