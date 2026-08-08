# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a NS-3 simulator for RDMA Network Load Balancing, specifically implementing the ConWeave system from the SIGCOMM'23 paper "Network Load Balancing with In-network Reordering Support for RDMA". The codebase includes implementations of various load balancing algorithms (ECMP, CONGA, LetFlow, ConWeave), congestion control mechanisms (DCQCN, HPCC, TIMELY), and RDMA protocol behaviors.

## Build System & Commands

The project uses the WAF build system. Key commands:

```bash
# Configure the build (with examples and tests)
./waf configure --build-profile=optimized

# Build the project
./waf build
# or simply
./waf

# Alternative using Makefile wrapper
make configure  # configure with examples and tests
make build      # build the project
make clean      # clean build artifacts
```

## Running Simulations

### Quick Start
```bash
# Run basic simulation suite (8 experiments, 0.05s runtime)
./autorun.sh

# Run with AI workload patterns
./autorun_ai.sh

# Run comprehensive experiments
./autorun_new.sh
```

### Custom Simulations
```bash
# Individual simulation with custom parameters
python3 run.py --simul_time 0.1 --netload 50 --topo leaf_spine_128_100G_OS2 --cc dcqcn --lb ecmp

# Get help for all available parameters
python3 run.py --h
```

### Analysis & Plotting
```bash
# Plot Flow Completion Time results
python3 analysis/plot_fct.py

# Plot queue usage analysis
python3 analysis/plot_queue.py

# Plot uplink utilization
python3 analysis/plot_uplink.py
```

## Architecture Overview

### Core Components

**Load Balancing Implementations** (`src/point-to-point/model/`):
- `switch-node.{h,cc}`: Main switching logic with multi-path routing (ECMP, DRILL) and packet trimming
- `conga-routing.{h,cc}`: CONGA congestion-aware load balancing
- `letflow-routing.{h,cc}`: LetFlow packet-level load balancing
- `conweave-routing.{h,cc}`: ConWeave with in-network reordering support
- `conweave-voq.{h,cc}`: Virtual Output Queue management for ConWeave

**RDMA Protocol Stack**:
- `rdma-hw.{h,cc}`: RDMA-enabled NIC behavior including congestion control, loss recovery, and out-of-order packet handling
- `rdma-queue-pair.{h,cc}`: RDMA queue pair management with timeout and slow start modes
- `switch-mmu.{h,cc}`: Switch Memory Management Unit with PFC support

**Network Infrastructure**:
- `qbb-net-device.{h,cc}`: Quantized congestion control network device
- `qbb-channel.{h,cc}`: Network channel with PFC capabilities

### Simulation Scripts

**Main Simulation** (`scratch/network-load-balance/`):
- `main.cc`: Primary NS-3 simulation script (113KB, contains main simulation logic)
- `ai-workload-*`: AI workload generation and tracking components

**Traffic Generation**:
- `traffic_gen/`: Traffic pattern generators
- `run.py`: Orchestrates traffic generation, simulation execution, and analysis

### Configuration Management

**Topology Files** (`config/`):
- `leaf_spine_*.txt`: Leaf-spine network topologies
- `fat_k*.txt`: Fat-tree topologies
- `*_topology_gen.py`: Scripts to generate custom topologies

**Experiment Configuration**:
- `run.py`: Contains comprehensive parameter templates and ConWeave-specific settings
- `autorun*.sh`: Predefined experiment suites with parallel execution

## Load Balancing Algorithms

The simulator supports multiple load balancing methods configurable via the `--lb` parameter:
- `ecmp`: Equal-Cost Multi-Path routing
- `letflow`: Packet-level load balancing
- `conga`: Congestion-aware load balancing
- `conweave`: In-network reordering with load balancing
- `drill`: Dynamic load balancing with in-order delivery

## Congestion Control

Supported algorithms (`--cc` parameter):
- `dcqcn`: Data Center Quantized Congestion Notification
- `hpcc`: High Precision Congestion Control
- `timely`: TIMELY congestion control

## Output Analysis

Simulation results are stored in `mix/output/[simulation-id]/` containing:
- `*_out_fct.txt`: Flow Completion Time data
- `*_out_pfc.txt`: Priority Flow Control events
- `*_out_uplink.txt`: Uplink utilization metrics
- `*_out_voq_*.txt`: Virtual Output Queue statistics
- `config.txt`: Simulation parameters used

## Development Notes

- The codebase implements accurate RNIC behavior for out-of-order packet sensitivity
- ConWeave parameters are automatically configured based on topology and flow control model
- Parallel simulation execution is supported via `autorun.sh` with configurable concurrency limits
