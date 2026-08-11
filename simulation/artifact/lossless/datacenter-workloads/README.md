# Lossless datacenter workloads

This workload family provides Figures 4--6, the three datacenter references
for Figure 8, Figure 9, and Tables 4--5. Run commands from `simulation/`.

## Experiments

| Scenario | Topology and workload | Paper outputs |
|---|---|---|
| A | 2:1 `leaf_spine_128_100G_OS2`, AliStorage2019 | Figure 4(a), Figure 5, Figure 6, Table 4 |
| B | `fat_k8_100G_OS1`, AliStorage2019 | Figure 4(b) |
| C | `fat_k8_100G_OS1`, Solar2022 | Figure 6 |
| D | 1:1 `leaf_spine_L8_S16_100G_OS1`, FbHdp2015 | Figure 6 |
| E | 1:1 `leaf_spine_L8_S16_100G_OS1`, AliStorage2019 | Figure 9, Table 5 |

Figure 8 also uses one AR reference for each of FbHdp2015, Solar2022, and
AliStorage2019 on the 1:1 leaf-spine topology. The AllToAllV inputs for that
figure belong to the sibling collective workload.

Each main scenario compares ECMP, ConWeave, DRILL, RPS, and AR. The common
configuration is 100 Gbps, 80% offered load, DCQCN, PFC enabled, and a 4 ms
RTO. The complete source of truth is the explicit `run_experiment_group` list
in `run_experiments.sh`; there are 28 simulations in total.

## Managed commands

Run simulations inside the detached Docker container:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage run \
  --run-id trial1
```

Monitor the same run from either Docker or the host:

```bash
./artifact/run_artifact.sh \
  --section lossless \
  --workload datacenter-workloads \
  --stage status \
  --run-id trial1
```

Parsing and plotting use existing outputs and can run on the host:

```bash
./artifact/lossless/datacenter-workloads/parse_results.sh --run-id trial1
./artifact/lossless/datacenter-workloads/plot_results.sh --run-id trial1
```

Use `--dry-run` with either command to print the parser or Bazel commands
without reading experiment results. The workload scripts are thin entry points
to the same managed `run_artifact.sh` workflow.

## Parser mapping

| Output | Raw input | Runs | Parser backend |
|---|---|---:|---|
| Figure 4 | FCT | 10 | `parse_dcn_fct_rto.py` |
| Figure 5 | OOO/drop | 5 | `parse_dcn_ooo.py` |
| Figure 6 | PFC pause | 15 | `parse_dcn_pfc_trigger.py` |
| Figure 9 | PFC incast queue | 5 | `parse_dcn_pfc_incast.py` |
| Table 4 | spine egress queue | 5 | `parse_dcn_spine_qlen.py` |
| Table 5 | spine PFC balance | 5 | `parse_dcn_pfc_spine_balance.py` |

The manifest records `paper_outputs` when each configuration starts. Parsers
join `manifest.csv` with `history/all.history` by `config_id`; they do not infer
figure ownership from topology or workload fields. Figure-specific histories
and legacy parser workspaces are created under `/tmp` and removed after use.

Figure 9 and Table 5 deliberately select the same five Scenario E runs. They
must not use the Figure 4(b) fat-tree data or Figure 8 AllToAllV-128 data.

## Results

```text
artifact/results/lossless/datacenter-workloads/runs/<run-id>/
  status
  status.json
  manifest.csv
  history/all.history
  logs/
  json/<semantic-output>/
  figures/
  tables/
```

`json/` contains parsed inputs only. Plot backends work in temporary copies and
only final paper PDFs are copied to `figures/`. Tables 4 and 5 are emitted as
CSV and Markdown under `tables/`.
