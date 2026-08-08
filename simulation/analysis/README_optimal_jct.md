# Optimal JCT Analyzer for AlltoallV Traffic Patterns

This tool calculates theoretical optimal Job Completion Time (JCT) for different AlltoallV traffic patterns, considering network topology constraints and traffic distribution imbalances.

## Usage

```bash
# Analyze all patterns with default settings
python3 analysis/optimal_jct_analyzer.py

# Compare all patterns with specific message size
python3 analysis/optimal_jct_analyzer.py --base_size 19660800 --group_size 8

# Analyze specific pattern
python3 analysis/optimal_jct_analyzer.py --pattern moe --base_size 1048576

# Specify topology
python3 analysis/optimal_jct_analyzer.py --topo leaf_spine_L8_S16_100G_OS1
```

## Traffic Patterns Analyzed

### 1. Uniform Pattern
- **Load balancing**: Perfect (1.00x factor)
- **Characteristics**: Each GPU sends/receives the same total amount
- **JCT**: Baseline optimal performance
- **Use case**: Ideal comparison reference

### 2. Zipfian Pattern
- **Load balancing**: Receiver imbalance (2.30x factor)
- **Characteristics**: Same send load per GPU, Zipfian receive distribution
- **JCT**: ~2.8x slower than uniform (for 18.8MB workload)
- **Use case**: Flow-level skew with elephant and mice flows

### 3. MoE (Incast) Pattern
- **Load balancing**: Receiver imbalance (2.47x factor)
- **Characteristics**: Uniform senders, Zipfian receivers (incast)
- **JCT**: ~3.7x slower than uniform (for 18.8MB workload)
- **Use case**: Realistic MoE expert popularity simulation

## Key Metrics

- **Optimal JCT**: Theoretical minimum completion time considering bottlenecks
- **Load Balance Factor**: Max load / Average load (1.0 = perfect balance)
- **Bottleneck Type**: Whether sender or receiver is the limiting factor
- **Traffic Distribution**: Actual bytes sent/received per GPU

## Example Results

For 18.8MB total per GPU on 8-GPU group:

| Pattern | Optimal JCT | Sender Time | Receiver Time | Load Balance (RX) |
|---------|-------------|-------------|---------------|-------------------|
| Uniform | 1.57 ms     | 1.57 ms     | 1.57 ms       | 1.00x             |
| Zipfian | 4.34 ms     | 1.57 ms     | 3.62 ms       | 2.30x             |
| MoE     | 5.84 ms     | 1.57 ms     | 3.89 ms       | 2.47x             |

## Network Considerations

- **Server Bandwidth**: 100 Gbps uplink (configurable)
- **Topology Awareness**: Fat-tree and leaf-spine support
- **Congestion Modeling**: Empirical penalties for incast patterns
- **Conservative Estimates**: Assumes server uplink as primary bottleneck

## Limitations

- Network fabric modeling is simplified (uses empirical congestion factors)
- Does not model detailed switch queueing or PFC behavior
- Assumes ideal load balancing within network fabric
- Real performance may vary due to packet-level effects and protocol overhead