# Lossy collective-communication workloads

This group reproduces Figure 13 with 47 simulations.

It evaluates AllToAll and RingAllReduce with groups of 8 and AllToAllV with
groups of 8, 16, 32, 64, and 128. The runs compare RTO, trimming, and
rate-reduction timeout modes at 400 Gbps with PFC disabled. Leaf-spine
AI windows are 404000 bytes, RingAllReduce uses 1024000 bytes, and RTOs are
`320 us`/`100 us`; AllToAllV uses the `zipfian_incast` pattern.

```bash
./artifact/lossy/collective-communication-workloads/run_experiments.sh
./artifact/lossy/collective-communication-workloads/parse_results.sh
./artifact/lossy/collective-communication-workloads/plot_results.sh
```

`parse_results.sh` runs `parse_jct_with_ideal.py` to produce Figure 13
JSON. Results are written below
`artifact/results/lossy/collective-communication-workloads/`.

`MAX_JOBS` is set near the top of `run_experiments.sh`. The runner follows
`autorun_ai.sh`, with every CC workload parameter group listed explicitly.
