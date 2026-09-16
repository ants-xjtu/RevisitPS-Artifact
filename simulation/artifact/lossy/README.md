# Lossy Experiments

Run commands from `simulation/`. Use Docker for `run` and `parse`, then use the
host with Bazel installed for `plot`:

```bash
./artifact/run_artifact.sh --section lossy --stage run --run-id trial1
./artifact/run_artifact.sh --section lossy --stage status --run-id trial1
./artifact/run_artifact.sh --section lossy --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossy --stage plot --run-id trial1
```

Use `--resume` with the run stage to continue an existing run. Use a unique
run ID when starting another lossy run concurrently.

Workload-specific commands:

- [Datacenter workloads](datacenter-workloads/README.md)
- [Collective communication workloads](collective-communication-workloads/README.md)
