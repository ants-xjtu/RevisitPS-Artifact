#!/usr/bin/env python3
"""
JCT Parser with Dynamic Ideal JCT Calculation

This script parses JCT results from NS-3 simulations and adds dynamic ideal JCT
baselines using the optimal_jct_analyzer module for accurate performance comparison.

Features:
- Parses JCT results from simulation output files
- Calculates dynamic ideal JCT using optimal_jct_analyzer
- Supports AlltoallV traffic patterns (uniform/zipfian/moe)
- Generates plots with proper ideal JCT reference lines
- Compatible with different topologies and message sizes
"""

import os
import sys
import argparse
import subprocess
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
from cycler import cycler

# Add current directory to path to import optimal_jct_analyzer
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from optimal_jct_analyzer import AlltoallVAnalyzer, NetworkTopology

# Plotting styles
lb_modes = {
    0: "fecmp", 1: "rps", 2: "drill", 3: "conga", 4: "adaptive", 6: "letflow", 9: "conweave",
}
irn_modes = {
    0: "N-Go-Back-N", 1: "IRN", 2: "DCP",
}
cc_modes = {
    1: "dcqcn", 4: "none",
}
C = [
    'xkcd:grass green', 'xkcd:blue', 'xkcd:purple', 'xkcd:orange', 'xkcd:teal',
    'xkcd:brick red', 'xkcd:black', 'xkcd:magenta', 'xkcd:brown', 'xkcd:sky blue',
    'xkcd:grey', 'xkcd:lime green', 'xkcd:gold', 'xkcd:royal blue', 'xkcd:pink'
]
LS = [
    'solid', 'dashed', 'dotted', 'dashdot',
    (0, (5, 5)), (0, (1, 1)), (0, (3, 5, 1, 5)), (0, (5, 10)), (0, (1, 10)),
    (0, (3, 10, 1, 10)), (5, (10, 3)), (0, (3, 1, 1, 1)), (0, (5, 1, 1, 1)),
    (0, (10, 5, 2, 5)), (0, (1, 5))
]
M = [
    'o', 's', 'x', 'v', 'D', '^', '<', '>',
    'p', 'P', '*', 'h', 'H', '+', '|'
]

def setup_plot_style():
    """Setup matplotlib plotting styles"""
    plt.rc('lines', markersize=6, linewidth=2.5)
    plt.rc('legend', handlelength=2, handleheight=1.5, labelspacing=0.25, fontsize=9)
    plt.rcParams["font.family"] = "sans"
    plt.rcParams["font.size"] = 10
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

def get_ranked_jct_data(filename, time_start, time_end):
    """Parse JCT data from simulation output file and rank by performance"""
    cmd_get_raw = f"cat {filename} | awk '{{ if ($3 > {time_start} && ($3 + $4) < {time_end}) print $1, $4}}'"
    jcts_by_round = defaultdict(list)

    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip():
            return {}

        for line in output_raw.strip().split('\n'):
            parts = line.split()
            round_id = int(parts[0])
            jct_ns = float(parts[1])
            jcts_by_round[round_id].append(jct_ns / 1000.0)  # Convert to microseconds

    except (subprocess.CalledProcessError, ValueError, IndexError):
        print(f"Warning: Command or parsing failed for {filename}. Returning empty dict.")
        return {}

    if not jcts_by_round:
        return {}

    # Rank JCTs within each round
    jcts_by_rank = defaultdict(list)
    for round_id, jct_list in jcts_by_round.items():
        sorted_jcts = sorted(jct_list)
        for rank, jct_value in enumerate(sorted_jcts):
            jcts_by_rank[rank].append(jct_value)

    # Calculate average JCT for each rank
    avg_jct_by_rank = {rank: np.mean(jct_values) for rank, jct_values in jcts_by_rank.items()}
    return avg_jct_by_rank

def calculate_dynamic_ideal_jct(workload, pattern, message_size, topology, group_size=8):
    """
    Calculate ideal JCT using optimal_jct_analyzer

    Args:
        workload: Workload type (e.g., "AlltoallV", "Alltoall")
        pattern: Traffic pattern (e.g., "uniform", "zipfian", "moe")
        message_size: Message size in bytes
        topology: Topology name
        group_size: Group size (default 8)

    Returns:
        ideal_jct_us: Ideal JCT in microseconds, or None if calculation fails
    """
    try:
        # Initialize analyzer
        topo = NetworkTopology(topology)
        analyzer = AlltoallVAnalyzer(topo)

        # Map workload to pattern if needed
        if workload == "AlltoallV":
            # Use the provided pattern
            analysis_pattern = pattern
        elif workload == "Alltoall":
            # Traditional alltoall is uniform
            analysis_pattern = "uniform"
        elif workload == "RingAllreduce":
            # Ring allreduce has different characteristics, use uniform as approximation
            analysis_pattern = "uniform"
            # For ring allreduce, message size should be adjusted for bidirectional communication
            message_size = message_size * 2  # Rough approximation
        else:
            print(f"Warning: Unknown workload {workload}, using uniform pattern")
            analysis_pattern = "uniform"

        # Generate traffic matrix and calculate ideal JCT
        traffic_matrix = analyzer.generate_traffic_matrix(analysis_pattern, message_size, group_size)
        results = analyzer.calculate_optimal_jct(traffic_matrix, analysis_pattern)

        # Return ideal JCT in microseconds
        ideal_jct_us = results['ideal_jct_ms'] * 1000  # Convert ms to μs

        print(f"Calculated ideal JCT for {workload} ({analysis_pattern}): {ideal_jct_us:.2f} μs")
        return ideal_jct_us

    except Exception as e:
        print(f"Warning: Failed to calculate ideal JCT for {workload} {pattern}: {e}")
        return None

def extract_pattern_from_filename(filename):
    """Extract traffic pattern from filename"""
    if "_uniform_" in filename:
        return "uniform"
    elif "_zipfian_" in filename:
        return "zipfian"
    elif "_moe_" in filename:
        return "moe"
    elif "_power2_" in filename:
        return "power2"
    elif "_linear_" in filename:
        return "linear"
    elif "_random_" in filename:
        return "random"
    else:
        return "uniform"  # Default

def main():
    parser = argparse.ArgumentParser(description='Parse JCT results with dynamic ideal JCT calculation')
    parser.add_argument('history_files', nargs='+', type=str, help='List of classified history files to process')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0, help='Start time limit')
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000, help='End time limit')
    parser.add_argument('--group_size', type=int, default=8, help='Group size for ideal JCT calculation')
    parser.add_argument('--topology', type=str, default='fat_k8_100G_OS1', help='Topology name for ideal JCT calculation')
    args = parser.parse_args()

    setup_plot_style()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "..", "mix", "output")
    fig_dir = os.path.join(script_dir, "figures_jct_with_ideal")
    os.makedirs(fig_dir, exist_ok=True)

    aggregated_results = defaultdict(dict)
    workload_pattern_by_size = {}  # Store workload and pattern for each message size
    common_params_str = ""

    print("Processing history files...")
    for history_filename in args.history_files:
        print(f"  Processing {os.path.basename(history_filename)}...")

        with open(history_filename, "r") as f:
            for line in f.readlines():
                if ',' not in line:
                    continue

                parsed = line.strip().split(',')
                if len(parsed) < 22:
                    continue

                try:
                    # Parse line components
                    config_id = parsed[1]
                    cc_mode_id = int(parsed[2])
                    lb_mode_id = int(parsed[3])
                    ar_mode = parsed[4]
                    irn = int(parsed[11])
                    current_workload = parsed[17]
                    message_size = int(parsed[18])

                    if lb_mode_id not in lb_modes:
                        continue

                    # Extract traffic pattern from config_id for AlltoallV workloads
                    if current_workload == "AlltoallV":
                        pattern = extract_pattern_from_filename(config_id)
                    else:
                        pattern = "uniform"  # Default for other workloads

                    # Store workload and pattern info for this message size
                    if message_size not in workload_pattern_by_size:
                        workload_pattern_by_size[message_size] = (current_workload, pattern)

                    # Create plot label
                    cc_label = cc_modes.get(cc_mode_id, "UnknownCC")
                    lb_label = lb_modes.get(lb_mode_id, "UnknownLB")
                    recovery_label = "AR-Go-Back-N" if ar_mode != '0' else irn_modes.get(irn, "Unknown")
                    plot_label = f"{lb_label}+{cc_label}+{recovery_label}"

                    # Parse JCT data
                    jct_file = os.path.join(output_dir, config_id, f"{config_id}_out_jct.txt")
                    if os.path.exists(jct_file):
                        avg_jct_by_rank = get_ranked_jct_data(jct_file, args.time_limit_begin, args.time_limit_end)
                        if avg_jct_by_rank:
                            sorted_ranks = sorted(avg_jct_by_rank.keys())
                            avg_jcts = [avg_jct_by_rank[r] for r in sorted_ranks]
                            aggregated_results[plot_label][message_size] = (sorted_ranks, avg_jcts)

                    # Extract common parameters for filename
                    if not common_params_str:
                        basename, _ = os.path.splitext(os.path.basename(history_filename))
                        parts = basename.split('_')
                        if len(parts) > 7:
                            common_params_str = f"TOPO_{parts[1]}_WORKLOAD_{parts[3]}_ERR_{parts[4]}_TMT_{parts[5]}_FC_{parts[6]}_WIN_{parts[7]}"
                        else:
                            common_params_str = "PARSED_RESULTS"

                except (ValueError, IndexError) as e:
                    print(f"Warning: Failed to parse line: {line.strip()}")
                    continue

    if not aggregated_results:
        print("\nERROR: No valid data was aggregated. Plotting cancelled.")
        return

    # Get all message sizes
    all_message_sizes = set(size for data in aggregated_results.values() for size in data)
    if not all_message_sizes:
        print("\nERROR: No data points to plot. Exiting.")
        return

    # Define plot order for algorithms
    ordered_labels = [
        "fecmp+dcqcn+N-Go-Back-N", "conga+dcqcn+N-Go-Back-N", "letflow+dcqcn+N-Go-Back-N",
        "conweave+dcqcn+N-Go-Back-N", "rps+dcqcn+AR-Go-Back-N", "drill+dcqcn+AR-Go-Back-N",
        "adaptive+dcqcn+AR-Go-Back-N", "rps+dcqcn+DCP", "drill+dcqcn+DCP",
        "adaptive+dcqcn+DCP", "rps+none+AR-Go-Back-N", "drill+none+AR-Go-Back-N",
        "adaptive+none+AR-Go-Back-N",
    ]

    # Create style mapping
    fixed_style_map = {label: {'color': C[i], 'linestyle': LS[i], 'marker': M[i]}
                       for i, label in enumerate(ordered_labels)}

    # Generate plots for each message size
    print(f"\nGenerating plots for {len(all_message_sizes)} message sizes...")

    for size in sorted(list(all_message_sizes)):
        print(f"  Generating plot for message size: {size} bytes...")

        fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
        ax.set_xlabel("Group Rank (0 = fastest)", fontsize=12)
        ax.set_ylabel("Average JCT (μs)", fontsize=12)

        # Get workload and pattern for this message size
        workload, pattern = workload_pattern_by_size.get(size, ("Unknown", "uniform"))
        ax.set_title(f"JCT vs. Rank for {workload} ({pattern}) - Message Size: {size} Bytes", fontsize=14)

        # Plot algorithm results
        for base_label in ordered_labels:
            style = fixed_style_map.get(base_label, {'color': 'black', 'linestyle': 'solid', 'marker': 'o'})

            if base_label in aggregated_results and size in aggregated_results[base_label]:
                ranks, avg_jcts = aggregated_results[base_label][size]
                ax.plot(ranks, avg_jcts, label=base_label, **style)

            # Also plot IRN variant if N-Go-Back-N exists
            if "N-Go-Back-N" in base_label:
                irn_label = base_label.replace("N-Go-Back-N", "IRN")
                if irn_label in aggregated_results and size in aggregated_results[irn_label]:
                    ranks, avg_jcts = aggregated_results[irn_label][size]
                    ax.plot(ranks, avg_jcts, label=irn_label, **style)

        # Add dynamic ideal JCT reference line
        ideal_jct_us = calculate_dynamic_ideal_jct(workload, pattern, size, args.topology, args.group_size)

        if ideal_jct_us is not None:
            ax.axhline(y=ideal_jct_us, color='red', linestyle=':', linewidth=3,
                      label=f'Ideal {workload} ({pattern}): {ideal_jct_us:.1f} μs')
            print(f"  Added ideal JCT reference line: {ideal_jct_us:.1f} μs")
        else:
            print(f"  Warning: Could not calculate ideal JCT for {workload} ({pattern})")

        # Finalize plot
        ax.legend(frameon=False, loc='best')
        ax.grid(which='major', linestyle='--', alpha=0.6)
        ax.set_yscale("log")

        # Save plot
        fig_filename = os.path.join(fig_dir, f"JCT_WITH_IDEAL_{common_params_str}_MSG_{size}_{pattern}.pdf")
        print(f"  Saving figure: {fig_filename}")
        fig.savefig(fig_filename, bbox_inches='tight', dpi=300)
        plt.close(fig)

    print(f"\nCompleted! Generated plots saved in: {fig_dir}")

if __name__ == "__main__":
    main()