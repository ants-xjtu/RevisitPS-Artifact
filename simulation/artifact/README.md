# Paper Artifact: Figures 4--17 and Tables 4--5

This directory contains the managed artifact workflow for
`nsdi27spring-paper67.pdf`. It is organized by paper section and workload
family. Runners enumerate paper experiment parameters explicitly, parsers
produce figure-specific JSON, and plot wrappers call the sibling Bazel
workspace in `../../plot`.

## Quick Start

Run from `simulation/`:

```bash
./artifact/run_artifact.sh --section all --stage all --dry-run
./artifact/run_artifact.sh --section lossless --stage all --run-id trial1
./artifact/run_artifact.sh --section lossless --workload datacenter-workloads --stage parse --run-id trial1
./artifact/run_artifact.sh --section lossless --stage status --run-id trial1
./artifact/run_artifact.sh --section lossy --stage all --run-id trial1
./artifact/run_artifact.sh --section asymmetric --stage all --run-id trial1
```

Options:

```text
--section lossless|lossy|asymmetric|all
--workload datacenter-workloads|collective-communication-workloads|all
--stage run|parse|plot|status|all
--run-id ID       result directory name; default is latest
--dry-run         print commands without running them
--spine-id ID     Figure 10 spine node; default is 136
```

## Artifact Map

| Section | Workload family | Paper outputs | Simulations |
|---|---|---|---:|
| Lossless | Datacenter | Figures 4--6, Figure 8 references, Figure 9, Tables 4--5 | 28 |
| Lossless | Collective communication | Figures 7, 8, 10 | 47 |
| Lossy | Datacenter | Figures 11--12 | 10 |
| Lossy | Collective communication | Figure 13 | 47 |
| Asymmetric | Datacenter | Figures 14--16 | 26 |
| Asymmetric | Collective communication | Figure 17 | 48 |

Figure 8 compares datacenter references with collective workloads. Its three
traditional-workload references belong to the datacenter runner, while its
AlltoallV inputs belong to the collective runner; the parser combines both
managed run directories.

Figure 9 and Table 5 use the same five 1:1
`leaf_spine_L8_S16_100G_OS1` AliStorage runs. Figure 9 compares queue length
per PFC event, while Table 5 reports spine pause balance. Neither output uses
the fat-tree Figure 4(b) runs or the AllToAllV-128 runs.

## Layout

```text
artifact/
|-- run_artifact.sh
|-- common/                       # shared matrix, history selection, table helpers
|-- lossless/
|   |-- datacenter-workloads/
|   `-- collective-communication-workloads/
|-- lossy/
|   |-- datacenter-workloads/
|   `-- collective-communication-workloads/
|-- asymmetric/
|   |-- datacenter-workloads/
|   `-- collective-communication-workloads/
`-- tests/
```

Each workload directory has:

- `run_experiments.sh`: launches explicit `python3 run.py ...` experiment groups.
- `parse_results.sh`: selects the relevant history rows and runs parser wrappers.
- `plot_results.sh`: calls only the matching plot workspace wrappers.

## Managed Results

Results are isolated by run id:

```text
artifact/results/<section>/<workload-family>/runs/<run-id>/
  status
  status.json
  logs/
  history/all.history
  manifest.csv
  json/<semantic-output>/
  figures/
  tables/
```

For lossless runs, `run.py` appends each parameter row under the selected
`run-id` when configuration starts, while retaining the shared `mix/.history`
compatibility log. At the same point, it appends the task metadata and new
`config_id` to `manifest.csv`; `paper_outputs` is therefore visible while the
experiments are still running, not reconstructed after they finish. File
locking keeps concurrent history and manifest append operations intact.
`status.json` records every task as running, completed, or failed and the plain
`status` file exposes the overall state. Different run IDs have independent
logs, histories, and status; a second invocation with the same run ID is
rejected. Parse refuses a tracked run until its state is `completed`.

`history/all.history` deliberately retains the simulator's fixed 24-column
format because the original parsers read fields by position. Paper ownership
is not inferred from those fields: `manifest.csv` records `paper_outputs` for
every `config_id`, and artifact parsers join the two files by `config_id` before
creating each figure-specific history. Keep these files together; the manifest
is the source of truth for Figure/Table selection.

Figure-specific history selections are temporary files, not managed results.
Legacy parsers run in temporary workspaces under `/tmp`, and plot wrappers use
temporary input/output workspaces. Successful commands remove those workspaces
automatically. Consequently, `json/<semantic-output>/` contains parsed inputs,
`figures/` contains only final paper PDFs, and parser source copies never appear
under `results/`.

Within each selected section, workload families run sequentially and each
family controls its own task parallelism. A failed family does not skip later
families; the run stage returns nonzero after all selected families are tried.


Raw simulator output remains in `mix/output/<config-id>/`. Generated results,
logs, JSON, figures, and Python caches are ignored by Git.

## Semantic Outputs

Lossless:

- `fig04_lossless_dcn_p99_fct`
- `fig05_lossless_ooo_degree`
- `fig06_lossless_pfc_pause_duration`
- `tbl04_lossless_avg_egress_queue`
- `fig07_lossless_ai_collective_cct`
- `fig08_lossless_pfc_incast_degree`
- `fig09_lossless_queue_per_pfc_event`
- `fig10_lossless_spine_queue_timeseries`
- `tbl05_lossless_spine_pause_balance`

Lossy:

- `fig11_lossy_dcn_p99_fct_leafspine`
- `fig12_lossy_dcn_p99_fct_fattree`
- `fig13_lossy_ai_collective_cct`

Asymmetric:

- `fig14_asym_dcn_fct`
- `fig15_asym_ooo_retransmission`
- `fig16_asym_packet_trim_rto`
- `fig17_asym_ai_collective_cct`

## Parameter Conventions

- Traditional datacenter traffic uses 100 Gbps and 80% load.
- Lossless/lossy collective communication uses 400 Gbps, `--buffer 0.32`, and
  150 MiB target receive volume per rank.
- Asymmetric collective communication uses 100 Gbps and `--buffer 0`.
- 400G AI windows are 404000 bytes for leaf-spine, 606000 bytes for fat-tree,
  and 1024000 bytes for RingAllReduce.
- Figure 17 uses 100G windows: 104000 bytes for Alltoall and 512000 bytes for
  RingAllReduce.
- Non-AR baselines (`armode noar`, ECMP/ConWeave) use timeout mode 0.
- Lossy AR RTO+GBN uses timeout mode 2 where the paper configuration requires it.

The source of truth is the explicit `run_experiment_group` lines in each
workload directory and `common/experiments_extended.csv`.

## Pipeline

```text
run.py
  -> mix/output/<config-id>/ raw logs
  -> runs/<run-id>/{status.json,history/all.history}
  -> artifact history selection
  -> parser/artifact/<section>/parse_*.py
  -> artifact-local JSON
  -> plot/main/plot_artifact/<section>/plot_*.py
  -> figures and tables
```

Parser wrappers stage legacy parsers when needed so generated JSON does not
pollute the repository-level `parser/` directories. These stages are temporary
and are not retained under the run directory. Each public `parse_results.sh`
and `plot_results.sh` is a thin workload-specific entry point to
`run_artifact.sh`.

## Validation

```bash
find artifact -name '*.sh' -type f -exec bash -n {} +
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s artifact/tests -p 'test_*.py' -v
./artifact/run_artifact.sh --section all --stage all --dry-run
```
