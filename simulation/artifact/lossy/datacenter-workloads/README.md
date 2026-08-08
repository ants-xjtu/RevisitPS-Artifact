# Lossy datacenter workloads

This group reproduces Figures 11--12 with 10 simulations.

- Figure 11: 1:1 leaf-spine, AliStorage2019 at 80% load.
- Figure 12: fat-tree k=8, AliStorage2019 at 80% load.

The runs use 100 Gbps, PFC disabled, DCQCN, `320 us` large-message RTO, and
`100 us` small-message RTO. The compared recovery configurations are the
paper's ECMP/ConWeave baselines and AR RTO/trimming variants.

```bash
./artifact/lossy/datacenter-workloads/run_experiments.sh
./artifact/lossy/datacenter-workloads/parse_results.sh
./artifact/lossy/datacenter-workloads/plot_results.sh
```

`parse_results.sh` runs `parse_dcn_fct_rto.py` and produces the Figure 11
and Figure 12 JSON before plotting. Results are written below
`artifact/results/lossy/datacenter-workloads/`.

`MAX_JOBS` is set near the top of `run_experiments.sh`. All Figure 11--12
parameter groups are listed directly in that script in `autorun_new.sh` form.
