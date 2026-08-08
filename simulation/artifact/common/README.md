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

`parse_paper_matrix.sh` calls the original parser programs and keeps JSON
artifact-local. The plot adapters never invoke parsers. Extended parse and
plot adapters accept repeatable `--figure` options; user-facing wrappers fix
these options to the paper outputs owned by their directory.

No shared script deletes `mix/output`. Existing parsers and plot workspace sources
are read-only dependencies.

Figures 4--6 and Table 4 are intentionally self-contained under
`artifact/lossless/datacenter-workloads/`; see that directory's README.
