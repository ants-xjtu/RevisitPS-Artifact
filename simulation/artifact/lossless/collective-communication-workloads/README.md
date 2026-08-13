# Lossless Collective-Communication Workloads

Run simulations inside Docker from `simulation/`:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload collective-communication-workloads \
  --stage run \
  --run-id trial1
```

Monitor or resume the run:

```bash
./artifact/run_artifact.sh --section lossless --workload collective-communication-workloads --stage status --run-id trial1
./artifact/run_artifact.sh --section lossless --workload collective-communication-workloads --stage run --run-id trial1 --resume
```

Parse and plot completed results from Docker or the host:

```bash
./artifact/lossless/collective-communication-workloads/parse_results.sh --run-id trial1
./artifact/lossless/collective-communication-workloads/plot_results.sh --run-id trial1
```

The lossless datacenter run with the same run ID must be available before
parsing this workload. Use `--spine-id ID` with the plot command only when a
different Figure 10 spine is needed.

Results are stored under
`artifact/results/lossless/collective-communication-workloads/runs/trial1/`.
