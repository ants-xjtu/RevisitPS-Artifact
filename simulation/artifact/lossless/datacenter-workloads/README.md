# Lossless Datacenter Workloads

Run commands from `simulation/`. Inside Docker, start the workload:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1
```

Inspect status or continue an interrupted run:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage status \
  --run-id trial1

./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1 \
  --resume
```

After the run completes, parse it inside Docker:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage parse \
  --run-id trial1
```

Then render the figures on the host with Bazel installed:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage plot \
  --run-id trial1
```

Results are stored under
`artifact/results/lossless/datacenter-workloads/runs/trial1/`.
