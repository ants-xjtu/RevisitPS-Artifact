# Lossless collective-communication workloads

This group reproduces the collective portions of Figures 7, 8, and 10 with 47
unique collective-communication simulations.

## Coverage

- Figure 7: normalized JCT for AllToAll, RingAllReduce, and AllToAllV.
- Figure 8: PFC incast comparison. This group supplies AllToAllV groups 8, 32,
  and 128; the parser reads Hadoop, RPC, and storage references from the
  sibling datacenter result directory.
- Figure 10: first-spine queue time series for AR without congestion control.

Collective runs use 400 Gbps, `--buffer 0.32`, a 150 MiB receive target,
404000-byte leaf-spine windows, 1024000-byte RingAllReduce windows, and
the paper's 4 ms (`4000 us`) lossless RTO. AllToAll and RingAllReduce use
groups of 8. AllToAllV uses groups of 8, 16, 32, 64, and 128 with the
`zipfian_incast` pattern.

## Managed commands

```bash
./artifact/run_artifact.sh --section lossless --workload collective-communication-workloads --stage run --run-id trial1
./artifact/lossless/collective-communication-workloads/parse_results.sh --run-id trial1
./artifact/lossless/collective-communication-workloads/plot_results.sh --run-id trial1
```

Run the lossless datacenter experiments before the standalone collective parse,
because Figure 8 requires the matching datacenter run's `manifest.csv` and
`history/all.history`. The managed workflow passes both run directories to the
Figure 8 parser.

Figure 10 defaults to spine node 136. Override it only for diagnostics:

```bash
./artifact/lossless/collective-communication-workloads/plot_results.sh --run-id trial1 --spine-id 137
```

`MAX_JOBS` is set near the top of `run_experiments.sh`. The runner follows
`autorun_ai_400.sh`: every experiment group and all of its parameters are listed
directly in the script. `plot_results.sh --dry-run` inspects the plotting
phase. `parse_results.sh` explicitly runs the JCT, PFC incast, and spine queue
parsers. Results are under
`artifact/results/lossless/collective-communication-workloads/runs/<run-id>/`.
Figure-specific selected histories and parser workspaces are temporary. Plot
intermediates are also temporary, so `json/` contains parsed data and
`figures/` contains final PDFs only.

Table 5 belongs to the sibling datacenter workflow because it uses 1:1
leaf-spine AliStorage data, not AllToAllV-128 data.
