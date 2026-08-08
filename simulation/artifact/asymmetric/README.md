# Asymmetric-network experiments

This section evaluates four asymmetric topologies:

- S1: one leaf-spine link failure.
- S2: 10% random link failures.
- S3: 10% of links limited to 50% capacity.
- S4: 20% of links limited to 50% capacity.

| Workload family | Paper outputs | Entry directory |
|---|---|---|
| Datacenter | Figures 14--16 | [datacenter-workloads](datacenter-workloads/README.md) |
| Collective communication | Figure 17 | [collective-communication-workloads](collective-communication-workloads/README.md) |

These are lossy runs with PFC disabled. Figure 16 reuses the S3 RTO baselines
from Figure 14 and adds the RPS/AR trimming configurations; duplicate
simulations are removed by the shared matrix expander.
