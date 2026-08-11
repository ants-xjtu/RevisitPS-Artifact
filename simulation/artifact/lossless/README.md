# Lossless experiments

This section uses PFC-enabled lossless fabrics.

| Workload family | Paper outputs | Entry directory |
|---|---|---|
| Datacenter | Figures 4--6, Figure 8 references, Figure 9, and Tables 4--5 | [datacenter-workloads](datacenter-workloads/README.md) |
| Collective communication | Figures 7, 8, and 10 | [collective-communication-workloads](collective-communication-workloads/README.md) |

Datacenter workloads use 100 Gbps links and 80% offered load. Collective
workloads use 400 Gbps links and a 150 MiB target receive volume. Figure 8 is a
cross-workload comparison: its Hadoop, RPC, and storage references come from
the datacenter result directory, and its AlltoallV panels come from the
collective-communication result directory.
Figure 9 and Table 5 share five 1:1 `leaf_spine_L8_S16_100G_OS1`
AliStorage configurations; they do not use Figure 4(b) or AllToAllV-128 data.

Run and monitor both groups from `simulation/`:

```bash
./artifact/run_artifact.sh --section lossless --stage run --run-id trial1
./artifact/run_artifact.sh --section lossless --stage status --run-id trial1
./artifact/run_artifact.sh --section lossless --workload datacenter-workloads --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossless --workload collective-communication-workloads --stage plot --run-id trial1
```
The datacenter group runs first, followed by collective communication; tasks
within each group run in parallel. If either group fails, the other group is
still attempted, and the command returns nonzero after both groups have
finished.


Each task writes its history row and state under
`artifact/results/lossless/<workload-family>/runs/trial1/` while it runs.
Use a unique run ID for each concurrent invocation; the same run ID cannot be
started twice.
