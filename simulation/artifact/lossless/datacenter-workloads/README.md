# Lossless datacenter workloads: Figures 4--6 and Table 4

This directory is a self-contained artifact pipeline for the paper's
lossless datacenter-workload evaluation. It does not use the shared runners in
`artifact/common/`.

```text
run_experiments.sh
  -> python3 run.py
  -> mix/output/<config-id>/{FCT, OOO, PFC, queue} raw logs
  -> parse_results.sh
  -> results/json/<figure>/*.json
  -> plot_results.sh
  -> plot Bazel targets
  -> results/figures/*.pdf
```

Run all commands below from the `simulation/` directory.

## 1. Run the experiments

`run_experiments.sh` directly follows the form of `autorun_new.sh`. The
bottom of the script contains eight explicit `run_experiment_group` lines.
Each line lists topology, load, error rate, workload, CC, PFC, IRN, AR mode,
timeout mode, window, both RTO values, buffer size, and LB algorithms in that
order. There are no runner command-line options or separate experiment files.

| Scenario | Topology | Workload | Used by |
|---|---|---|---|
| A | `leaf_spine_128_100G_OS2` (2:1) | AliStorage2019, 80% | Figure 4(a), Figure 5, Figure 6, Table 4 |
| B | `fat_k8_100G_OS1` (k=8) | AliStorage2019, 80% | Figure 4(b) |
| C | `fat_k8_100G_OS1` (k=8) | Solar2022, 80% | Figure 6 RPC |
| D | `leaf_spine_L8_S16_100G_OS1` (1:1) | FbHdp2015, 80% | Figure 6 Hadoop |

Each scenario runs the following five configurations:

| Paper label | `run.py --lb` | `--armode` | Recovery |
|---|---|---|---|
| ECMP | `fecmp` | `noar` | NAK+GBN |
| ConWeave | `conweave` | `noar` | NAK+GBN |
| DRILL | `drill` | `ar` | DDP + RTO+GBN |
| RPS | `rps` | `ar` | DDP + RTO+GBN |
| AR | `adaptive` | `ar` | DDP + RTO+GBN |

Common parameters:

- `--cc dcqcn --pfc 1 --irn 0`
- `--bw 100 --netload 80 --simul_time 0.05`
- `--error_rate 0.000 --flowgen_mode src`
- `--buffer 0`, selecting the simulator's 9 MB shared-buffer path
- `--windowSize 104000` for leaf-spine and `156000` for fat-tree
- `--rto_high 4000 --rto_low 4000`: paper/autorun 4 ms, where
  1 ms = 1000 us

Run all 20 simulations:

```bash
./artifact/lossless/datacenter-workloads/run_experiments.sh
```

Set `MAX_JOBS` near the top of the script to change the concurrency limit.
The runner writes one parameter-named log per task and the exact 20-row history
used by the parsers:

```text
results/logs/topo=..._load=..._cdf=..._lb=....log
results/lossless_datacenter.history
```

## 2. Parse raw data into JSON

Run:

```bash
./artifact/lossless/datacenter-workloads/parse_results.sh
```

The script first splits `lossless_datacenter.history` into figure-specific
history files, then invokes these parsers:

| Output | Raw ns-3 file | History rows | Parser | JSON output |
|---|---|---:|---|---|
| Figure 4 | `<id>_out_fct.txt` | A+B: 10 | `parse_dcn_fct_rto.py` | `results/json/figure4/*.json` |
| Figure 5 | `<id>_out_flow_drop.txt` | A: 5 | `parse_dcn_ooo.py` | `results/json/figure5/figure5.json` |
| Figure 6 | `<id>_out_pfc.txt` | C+A+D: 15 | `parse_dcn_pfc_trigger.py` | `results/json/figure6/*.json` |
| Table 4 | `<id>_out_qlen.txt` | A: 5 | `parse_dcn_spine_qlen.py` | `results/json/table4/table4.json` |

The Figure 4 parser supports an explicit output directory, so the actual call
is:

```bash
python3 parser/parse_dcn_fct_rto.py \
  artifact/lossless/datacenter-workloads/results/selected_history/figure4.history \
  -o artifact/lossless/datacenter-workloads/results/json/figure4
```

The Figure 5, Figure 6, and Table 4 parsers have hard-coded output directories.
`parse_results.sh` therefore copies each parser unchanged into
`results/parser_stage/<figure>/parser/`, links the read-only `mix/`,
`config/`, and `analysis/` inputs, and executes the copied parser. The
resulting JSON is then copied into the normalized `results/json/` paths in
the table above. Existing source files under `parser/` are not modified.

Table 4 has no plot: [build_table4.py](build_table4.py) reads the queue JSON
produced by `parse_dcn_spine_qlen.py` and writes:

```text
results/tables/table4.csv
results/tables/table4.md
```

Inspect the parser commands without requiring experiment output:

```bash
./artifact/lossless/datacenter-workloads/parse_results.sh --dry-run
```

## 3. Plot the parser JSON

Run:

```bash
./artifact/lossless/datacenter-workloads/plot_results.sh
```

The script invokes only these existing plot targets:

| Paper output | JSON input | Bazel target |
|---|---|---|
| Figure 4(a)/(b) | `results/json/figure4/` | `//main/plot_sample:plot_dcn_fct` |
| Figure 5 | `results/json/figure5/figure5.json` | `//main/plot_sample:plot_dcn_ooo` |
| Figure 6 | `results/json/figure6/` | `//main/plot_sample:plot_dcn_pfc_trigger` |

Equivalent commands are executed from the sibling `plot/`:

```bash
bazel run //main/plot_sample:plot_dcn_fct -- <figure4-json-directory>
bazel run //main/plot_sample:plot_dcn_ooo -- <figure5-json>
bazel run //main/plot_sample:plot_dcn_pfc_trigger -- <figure6-json-directory>
```

Inspect these commands without running Bazel:

```bash
./artifact/lossless/datacenter-workloads/plot_results.sh --dry-run
```

Final paper-facing files are collected under:

```text
results/figures/figure4a_p99_fct.pdf
results/figures/figure4b_p99_fct.pdf
results/figures/figure5_ooo_degree.pdf
results/figures/figure6_pause_duration.pdf
```

## Complete sequence

```bash
./artifact/lossless/datacenter-workloads/run_experiments.sh
./artifact/lossless/datacenter-workloads/parse_results.sh
./artifact/lossless/datacenter-workloads/plot_results.sh
```

The full ns-3 experiments, parsers, and Bazel plots were not executed during
script preparation.
