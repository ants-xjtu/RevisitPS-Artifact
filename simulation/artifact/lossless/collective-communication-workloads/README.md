# Lossless collective-communication workloads

This group reproduces Figures 7--10 and Table 5 with 50 unique simulations.

## Coverage

- Figure 7: normalized JCT for AllToAll, RingAllReduce, and AllToAllV.
- Figure 8: PFC incast comparison. The group includes Hadoop, RPC, storage,
  and AllToAllV groups 8, 32, and 128 because they are panels in the same
  cross-workload figure.
- Figure 9: AllToAllV-128 PFC/queue distribution.
- Figure 10: first-spine queue time series for AR without congestion control.
- Table 5: AllToAllV-128 spine pause time and coefficient of variation.

Collective runs use 400 Gbps, `--buffer 0.32`, a 150 MiB receive target,
404000-byte leaf-spine windows, 1024000-byte RingAllReduce windows, and
the paper's 4 ms (`4000 us`) lossless RTO. AllToAll and RingAllReduce use
groups of 8. AllToAllV uses groups of 8, 16, 32, 64, and 128 with the
`zipfian_incast` pattern.

## Run

```bash
./artifact/lossless/collective-communication-workloads/run_experiments.sh
./artifact/lossless/collective-communication-workloads/parse_results.sh
./artifact/lossless/collective-communication-workloads/plot_results.sh
```

Figure 10 defaults to spine node 136. Override it only for diagnostics:

```bash
./artifact/lossless/collective-communication-workloads/plot_results.sh --spine-id 137
```

`MAX_JOBS` is set near the top of `run_experiments.sh`. The runner follows
`autorun_ai_400.sh`: every experiment group and all of its parameters are listed
directly in the script. `plot_results.sh --dry-run` inspects the plotting
phase. `parse_results.sh` explicitly runs the JCT, PFC
incast, spine queue, and spine-balance parsers. Results and Table 5 are under
`artifact/results/lossless/collective-communication-workloads/`.
