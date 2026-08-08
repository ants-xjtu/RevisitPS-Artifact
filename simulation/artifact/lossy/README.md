# Lossy experiments

This section disables PFC and evaluates RTO, trimming, and rate-reduction
recovery.

| Workload family | Paper outputs | Entry directory |
|---|---|---|
| Datacenter | Figures 11--12 | [datacenter-workloads](datacenter-workloads/README.md) |
| Collective communication | Figure 13 | [collective-communication-workloads](collective-communication-workloads/README.md) |

Both groups use `320 us` as the large-message RTO and `100 us` as the
small-message RTO. The datacenter runs use 100 Gbps; collective runs use
400 Gbps.
