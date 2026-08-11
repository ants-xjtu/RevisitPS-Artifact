# Shared artifact implementation

Files in this directory provide shared parser and plotting support. Each
user-facing workload directory now owns its explicit autorun-style experiment
runner.

## Sources of truth

- `experiments_extended.csv`: retained as an audit/reference matrix for
  Figures 7--17 and Table 5.

`run_paper_matrix.py` is retained as an internal matrix inspection utility.
The workload runners no longer call it; they execute `python3 run.py ...`
directly and record the manifest required by the parse phase.

## Parser and plot mapping

| Paper output | Existing parser reused | Monorepo target/output |
|---|---|---|
| Figure 4 | `parse_dcn_fct_rto.py` | `plot_dcn_fct` |
| Figure 5 | `parse_dcn_ooo.py` | `plot_dcn_ooo` |
| Figure 6 | `parse_dcn_pfc_trigger.py` | `plot_dcn_pfc_trigger` |
| Table 4 | `parse_dcn_spine_qlen.py`, then `build_table4.py` | artifact CSV/Markdown |
| Figure 7 | `parse_jct_with_ideal.py` | `plot_sim_ai_jct_avg` |
| Figures 8--9 | `parse_dcn_pfc_incast.py` | `plot_dcn_pfc_incast` |
| Table 5 | `parse_dcn_pfc_spine_balance.py` | `build_table5.py` |
| Figure 10 | `parse_single_spine_qlen.py` | `plot_single_spine_qlen` |
| Figures 11--12 | `parse_dcn_fct_rto.py` | `plot_dcn_rto_fct` |
| Figure 13 | `parse_jct_with_ideal.py` | `plot_sim_ai_jct_avg` |
| Figure 14 | `parse_dcn_fct_rto.py` | `plot_dcn_rto_fct` |
| Figure 15 | `parse_dcn_ooo.py`, `parse_unnecc_retrans.py` | matching OOO/retransmission targets |
| Figure 16 | `parse_dcn_fct_rto.py` | `plot_dcn_rto_fct_trim_vs_rto` |
| Figure 17 | `parse_jct_with_ideal.py` | `plot_sim_ai_jct_avg_asy` |

`parse_dcn_qlen.py` remains an optional per-configuration diagnostic and is
not part of the Table 4 reproduction path.

## Internal interfaces

Figure-specific wrappers under `simulation/parser/artifact/` select manifest
rows and invoke the original parser programs in temporary workspaces. Public
`parse_results.sh` and `plot_results.sh` scripts forward their section and
workload to `run_artifact.sh`. The older matrix adapters remain only for
compatibility and are not part of the managed workflow.

The original `mix/.history` row layout is a compatibility interface and has no
paper-output column. Each runner therefore writes a sidecar manifest containing
`paper_outputs`. The runner passes this metadata into `run.py`, which appends
the manifest row as soon as it generates the `config_id` and writes the history
row. `run_manifest.py` locks concurrent CSV appends, and `select_history.py`
joins the manifest to history by `config_id`. Parser wrappers must use this
join instead of reconstructing Figure/Table membership from positional history
fields.

No shared script deletes `mix/output`. Existing parsers and plot workspace sources
are read-only dependencies.

Figures 4--6 and Table 4 are self-contained under
`artifact/lossless/datacenter-workloads/`. That directory also owns the three
traditional-workload references consumed by the cross-workload Figure 8
parser; see its README.
