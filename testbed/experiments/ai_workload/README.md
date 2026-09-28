# AI workload

```bash
# Run from testbed/ after prepare and check.
./run.sh --experiment ai_workload --workload all --network-mode all --run-id trial1 --stage all
```

`experiment.yaml` explicitly registers the three workloads and six network
profiles. BigSwitch/ECMP/RPS × lossless/lossy with DCQCN enabled was selected for
this refactor; historical result filenames are not used to invent combinations.
`configs/groups.yaml` references the shared deployment inventory by endpoint IP.
Rankfiles preserve the original CPU socket/core bindings and rank ordering.

The original C++ sources are unchanged. Each launch has 16 ranks in two concurrent
8-rank groups, using the original world/group barriers and ring order. Defaults
in `configs/workloads/150mib.yaml` remain 20 warmups and 500 measured iterations.
Ring/alltoallv use 157,286,400 bytes; alltoall uses integer division by seven,
22,469,485 bytes per peer. Zipf alpha remains 0.8.

Container compilation replaces compilation on dc20. Builds are keyed by sources,
flags, compiler/runtime identity and actual target descriptions. The container
sends binaries/configurations directly to every rank host and verifies SHA-256.
The configured launcher (default dc20) runs MPI through SSH. Every group leader
must reside there. Runtime probing selects a common RoCE v2 GID; the current
programs explicitly reject configurations without a common index.

Hardware configuration is now managed: the framework acquires the shared device
lock, validates dependencies/SSH/CPU binding/memlock, applies switch and NIC
settings and performs an RDMA smoke test before formal measurement. The launcher
needs independent SSH credentials; container agent forwarding is not used.

Results return to `results/ai_workload/<run-id>`. Each task/retry has separate raw
CSVs and logs. The parser checks sample count and validity; JCT is in microseconds,
p99 is nearest-rank, and groups/repeats are never pooled. `parse`, `plot`, `status`
and dry-run are offline. Existing run IDs require explicit verified resume.

`reference_results/` contains unchanged historical raw files and their existing
summary. These are readable evidence, not resumable task state or a network
configuration registry. See the [testbed guide](../../README.md) for the complete
startup sequence and matching MPI/container toolchain requirements.
