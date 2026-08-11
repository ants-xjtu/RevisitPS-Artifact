# Asymmetric datacenter workloads

This group reproduces Figures 14--16 with 26 simulations.

- Figure 14: FbHdp2015 at 80% load across S1--S4.
- Figure 15: out-of-order behavior in S3 and retransmission breakdown across
  S1--S4.
- Figure 16: S3 RTO baselines plus RPS/AR trimming.

The group uses the 1:1 leaf-spine topology family, 100 Gbps links, PFC
disabled, a 104000-byte window, and `320 us`/`100 us` lossy RTOs.
Shared Figure 14/15/16 configurations are executed once.

```bash
./artifact/run_artifact.sh --section asymmetric --workload datacenter-workloads --stage run --run-id trial1
./artifact/asymmetric/datacenter-workloads/parse_results.sh --run-id trial1
./artifact/asymmetric/datacenter-workloads/plot_results.sh --run-id trial1
```

`parse_results.sh` runs the FCT, OOO, and unnecessary-retransmission parsers
before any plot target is called. Results are written below
`artifact/results/asymmetric/datacenter-workloads/runs/trial1/`.

`MAX_JOBS` is set near the top of `run_experiments.sh`. The S1--S4
topologies and parameter groups are listed directly in the form used by
`autorun_asy.sh`.
