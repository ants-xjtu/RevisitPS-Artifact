# Asymmetric Datacenter Workloads

Run simulations inside Docker from `simulation/`:

```bash
./artifact/run_artifact.sh \
  --section asymmetric \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1
```

Monitor or resume the run:

```bash
./artifact/run_artifact.sh --section asymmetric --workload datacenter-workloads --stage status --run-id trial1
./artifact/run_artifact.sh --section asymmetric --workload datacenter-workloads --stage run --run-id trial1 --resume
```

Parse and plot completed results from Docker or the host:

```bash
./artifact/asymmetric/datacenter-workloads/parse_results.sh --run-id trial1
./artifact/asymmetric/datacenter-workloads/plot_results.sh --run-id trial1
```

Results are stored under
`artifact/results/asymmetric/datacenter-workloads/runs/trial1/`.
