# Asymmetric collective-communication workloads

This group reproduces Figure 17 with 48 simulations.

AllToAll and RingAllReduce use groups of 8 and run across S1--S4. The compared
load-balancing schemes are ECMP, ConWeave, RPS, AR, DRILLGroup, and SGLB.
Runs use 100 Gbps, `--buffer 0`, PFC disabled, a 150 MiB receive target,
104000-byte leaf-spine windows, 512000-byte RingAllReduce windows, and
`320 us`/`100 us` lossy RTOs.

```bash
./artifact/asymmetric/collective-communication-workloads/run_experiments.sh
./artifact/asymmetric/collective-communication-workloads/parse_results.sh
./artifact/asymmetric/collective-communication-workloads/plot_results.sh
```

`parse_results.sh` runs `parse_jct_with_ideal.py` to produce Figure 17
JSON. Results are written below
`artifact/results/asymmetric/collective-communication-workloads/`.

`MAX_JOBS` is set near the top of `run_experiments.sh`. Its explicit
parameter lines combine the CC form from `autorun_ai.sh` with the S1--S4
topologies and algorithms from `autorun_ai_asy.sh`.
