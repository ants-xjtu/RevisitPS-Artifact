# Lossy Collective-Communication Workloads

Run simulations inside Docker from `simulation/`:

```bash
./artifact/run_artifact.sh \
  --section lossy \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1
```

Monitor or resume the run:

```bash
./artifact/run_artifact.sh --section lossy --workload collective-communication-workloads --stage status --run-id trial1
./artifact/run_artifact.sh --section lossy --workload collective-communication-workloads --stage run --run-id trial1 --resume
```

Parse and plot completed results from Docker or the host:

```bash
./artifact/lossy/collective-communication-workloads/parse_results.sh --run-id trial1
./artifact/lossy/collective-communication-workloads/plot_results.sh --run-id trial1
```

Results are stored under
`artifact/results/lossy/collective-communication-workloads/runs/trial1/`.
