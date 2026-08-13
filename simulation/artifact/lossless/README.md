# Lossless Experiments

Run commands from `simulation/`:

```bash
./artifact/run_artifact.sh --section lossless --stage run --run-id trial1
./artifact/run_artifact.sh --section lossless --stage status --run-id trial1
./artifact/run_artifact.sh --section lossless --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossless --stage plot --run-id trial1
```

Use `--resume` with the run stage to continue an existing run. Use a unique
run ID when starting another lossless run concurrently.

Workload-specific commands:

- [Datacenter workloads](datacenter-workloads/README.md)
- [Collective communication workloads](collective-communication-workloads/README.md)
