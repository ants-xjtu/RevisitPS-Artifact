# DCN workload

The matrix in `experiment.yaml` selects BigSwitch, ECMP and RPS in lossless/lossy
modes. Run from `testbed` with:

```bash
./run.sh --experiment dcn_workload --network-mode all --run-id trial1 --stage all
```

Only the paper's Figure 2 configuration and connections are retained:

- `configs/tests/lossless.yaml` and `lossy.yaml` hold the shared
  traffic and measurement parameters for each mode.
- `configs/connections/fully_connected.yaml` defines the 64 connections between
  eight senders and eight receivers.

The BigSwitch switch/topology paths in the base configs are defaults.
`experiment.yaml` expands each mode into BigSwitch, ECMP and RPS variants;
`config_overrides` replaces those paths before validation and execution. ECMP
and RPS use their respective switch configs and the two-leaf/eight-spine topology.
Thus `--network-mode all` runs six configurations per repeat. The old per-algorithm
WebSearch presets and unused incast, mesh and point-to-point connections are
removed; the paper parameters and variant overrides are unchanged.

The former network-mode `--experiment` option is now `--network-mode`. The old
`docker_artifact.sh` command translates its arguments into the unified CLI.

Measurement order remains trace generation → validation → synchronization →
remote perftest → log collection → FCT parsing → Figure 2 plotting. Traffic
parameters, load, seed/repeat behavior, connection matrix, source code and FCT
statistics are preserved. `sources/perftest` remains the same pinned Git submodule
(commit `253a6c620ebbc0181ea366b088b2ab67572b9ce1`) and is built on RDMA nodes.

Results now live at `results/dcn_workload/<run-id>`. The `figure2` name remains
only for paper-specific metadata, bucket statistics and figure filenames.
`scripts/` contains the active trace generation/synchronization, execution,
FCT analysis, Figure 2 plotting and throughput diagnostics, plus their shared
helpers. Unused historical merge/FCT/CDF tools have been removed. See the
[testbed guide](../../README.md) for prepare/check, diagnostics, resume and SSH
configuration.
