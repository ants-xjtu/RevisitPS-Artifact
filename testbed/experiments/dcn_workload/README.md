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
remote perftest → log collection → FCT parsing → FCT plotting. Traffic
parameters, load, seed/repeat behavior, connection matrix, source code and FCT
statistics are preserved. `sources/perftest` remains the same pinned Git submodule
(commit `253a6c620ebbc0181ea366b088b2ab67572b9ce1`) and is built on RDMA nodes.

Results live at `results/dcn_workload/<run-id>`. Parsed summaries use
`parsed/fct.json` and `parsed/fct.csv`; size-bucket statistics use
`parsed/fct-buckets.json` and `parsed/fct-buckets.csv`. Plot outputs are
`figures/fct-lossless.*`, `figures/fct-lossy.*`, and the combined `figures/fct.*`
(when both modes are present), with normalized data in `figures/fct-source.csv`.
Names follow workload/metric semantics; paper figure references are retained only
in documentation and `paper_parameters` metadata. For older results, rerun
`--stage parse` before `--stage plot` to produce the renamed bucket files.
`scripts/` contains the active trace generation/synchronization, execution,
FCT analysis, FCT plotting and throughput diagnostics, plus their shared
helpers. Unused historical merge/FCT/CDF tools have been removed. See the
[testbed guide](../../README.md) for prepare/check, diagnostics, resume and SSH
configuration.

FCT analysis follows the original testbed scripts at commit `09cf327`: each
sender CSV drops its final physical line, sorts by `start_time`, and computes
`end_time - max(start_time, previous_end_time)` (the first row uses `end-start`).
Units are microseconds. Summary statistics exclude size/FCT values >= 1e9 and
use NumPy percentiles. FCT plotting floors FCT at 1, interleaves sorted FCTs in 100
sub-buckets within each size, then forms 19 equal-count buckets and uses the
discrete element at `int(n * 0.99)`. The historical upper cutoff is disabled.
Raw trace validation explicitly retains all rows and checks the original
timestamps; the analysis-only last-line omission does not mask incomplete runs.

DCN status polling, cleanup, counter reads and log transfers are batched by
management host. Completed process statuses are reused during polling. Cleanup
retains each process's PID/start-time/token checks, overlaps termination grace
periods, and verifies that no owned traffic remains before the next task.
Post-traffic counters are captured before directory log transfers; required
endpoint logs and sender CSVs are still checked individually. Trace hashes are
computed during input validation and verified with one checksum manifest per
sending host. SSH request pacing remains enabled, and command logs include
`pacing_seconds` separately from command execution time. Resume recovery also
uses host batches. No changes to the perftest workload or measurement parameters
are required.
