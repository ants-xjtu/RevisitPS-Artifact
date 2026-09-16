# Asymmetric Collective-Communication Workloads

Run commands from `simulation/`. Inside Docker, start the workload:

```bash
./artifact/run_artifact.sh \
  --section asymmetric \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1
```

Inspect status or continue an interrupted run:

```bash
./artifact/run_artifact.sh \
  --section asymmetric \
  --workload collective-communication-workloads \
  --stage status \
  --run-id trial1

./artifact/run_artifact.sh \
  --section asymmetric \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1 \
  --resume
```

After the run completes, parse it inside Docker:

```bash
./artifact/run_artifact.sh \
  --section asymmetric \
  --workload collective-communication-workloads \
  --stage parse \
  --run-id trial1
```

Then render the figure on the host with Bazel installed:

```bash
./artifact/run_artifact.sh \
  --section asymmetric \
  --workload collective-communication-workloads \
  --stage plot \
  --run-id trial1
```

Results are stored under
`artifact/results/asymmetric/collective-communication-workloads/runs/trial1/`.
