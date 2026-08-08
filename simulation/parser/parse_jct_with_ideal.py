#!/usr/bin/python3
"""
JCT Parser with Integrated Ideal JCT Calculation

This script parses JCT results from NS-3 simulations and integrates ideal JCT
calculations for AlltoallV and AllReduce workloads using the optimal_jct_analyzer.

Features:
- Parses JCT results from simulation history files
- Calculates ideal JCT using optimal_jct_analyzer for each group
- Supports AlltoallV traffic patterns (uniform/zipfian/moe)
- Supports Tree AllReduce and Ring AllReduce workloads
- Outputs JSON files with both experimental and ideal JCT data
- Compatible with existing plotting infrastructure
"""

import subprocess
import os
import sys
import argparse
import json
import numpy as np
from collections import defaultdict

# Add analysis directory to path to import optimal_jct_analyzer
script_dir = os.path.dirname(os.path.abspath(__file__))
analysis_dir = os.path.join(script_dir, "..", "analysis")
sys.path.append(analysis_dir)

try:
    from optimal_jct_analyzer import AlltoallVAnalyzer, TreeAllReduceAnalyzer, NetworkTopology
except ImportError as e:
    print(f"Warning: Could not import optimal_jct_analyzer: {e}")
    print("Ideal JCT calculation will be disabled.")
    AlltoallVAnalyzer = None
    TreeAllReduceAnalyzer = None
    NetworkTopology = None

# --- Dictionaries for mode mapping (consistent with provided scripts) ---
cc_modes = {
    1: "dcqcn", 2: "dcqcn_dst", 3: "hp", 4: "none", 7: "timely", 8: "dctcp",
}
cc_names = {
    "dcqcn": "DCQCN", "dcqcn_dst": "DCQCN_DST", "hp": "HPCC", "none": "NONE",
    "timely": "TIMELY", "dctcp": "DCTCP"
}
lb_modes = {
    0: "ECMP", 1: "RPS", 2: "DRILL", 3: "CONGA", 4: "AR", 5:"WAR", 6: "LetFlow", 7: "DRILLGroup", 9: "ConWeave", 10: "SGLB",
}
irn_modes = {
    0: "NAK+GBN", 1: "NAK+SR", 2: "DCP", 3: "Ideal",
}
# -----------------------------------------

def get_file_path():
    """Returns the directory path of the current script."""
    return os.path.dirname(os.path.realpath(__file__))

def extract_pattern_from_message_sizes_filename(msg_sizes_file):
    """
    Extract traffic pattern from the message sizes filename

    Args:
        msg_sizes_file: Path to *_alltoallv_msg_sizes.txt file

    Returns:
        str: Traffic pattern extracted from filename
    """
    filename = os.path.basename(msg_sizes_file).lower()

    # Check for pattern keywords in filename
    if "uniform" in filename:
        return "uniform"
    elif "zipfian" in filename or "zipf" in filename:
        return "zipfian"
    elif "moe" in filename:
        return "moe"
    elif "power2" in filename:
        return "power2"
    elif "linear" in filename:
        return "linear"
    elif "random" in filename:
        return "random"

    # If pattern not in filename, try parent directory
    parent_dir = os.path.dirname(msg_sizes_file).lower()
    if "uniform" in parent_dir:
        return "uniform"
    elif "zipfian" in parent_dir or "zipf" in parent_dir:
        return "zipfian"
    elif "moe" in parent_dir:
        return "moe"
    elif "power2" in parent_dir:
        return "power2"

    return "unknown"

def get_group_size_from_message_sizes(msg_sizes_file):
    """
    Infer group size from the message sizes file header comment.
    Looks for lines like '# Group 0: N nodes'.

    Args:
        msg_sizes_file: Path to *_alltoallv_msg_sizes.txt file

    Returns:
        int: Number of nodes in group 0, or None if file is unavailable
    """
    if not os.path.exists(msg_sizes_file):
        return None
    try:
        with open(msg_sizes_file, 'r') as f:
            for line in f:
                # Parse header like: # Group 0: 8 nodes
                if line.startswith('# Group 0:'):
                    parts = line.strip().split()
                    # "# Group 0: N nodes" -> parts[3] is N
                    return int(parts[3])
                # Stop scanning once we hit data lines
                if line.strip() and not line.startswith('#'):
                    break
        return None
    except Exception as e:
        print(f"Warning: Failed to infer group size from {msg_sizes_file}: {e}")
        return None


def calculate_ideal_jct_from_message_sizes(msg_sizes_file, link_bandwidth_gbps=100):
    """
    Calculate ideal JCT based on the maximum receiving node's receiving time

    Args:
        msg_sizes_file: Path to *_alltoallv_msg_sizes.txt file
        link_bandwidth_gbps: Link bandwidth in Gbps (default 100)

    Returns:
        ideal_jct_us: Ideal JCT in microseconds
    """
    if not os.path.exists(msg_sizes_file):
        return None

    try:
        with open(msg_sizes_file, 'r') as f:
            lines = f.readlines()

        # Calculate total bytes received by each node in first group
        recv_bytes_per_node = {}

        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split()
            if len(parts) >= 4:
                group_id = int(parts[0])
                if group_id > 0:  # Only analyze first group
                    break
                src_node = int(parts[1])
                dst_node = int(parts[2])
                msg_size = int(parts[3])

                if dst_node not in recv_bytes_per_node:
                    recv_bytes_per_node[dst_node] = 0
                recv_bytes_per_node[dst_node] += msg_size

        if not recv_bytes_per_node:
            return None

        # Find maximum receiving bytes
        max_recv_bytes = max(recv_bytes_per_node.values())

        # Calculate ideal time: max_recv_bytes / bandwidth
        # bandwidth in bytes/second = (link_bandwidth_gbps * 1e9 / 8)
        bandwidth_bytes_per_sec = link_bandwidth_gbps * 1e9 / 8
        ideal_time_sec = max_recv_bytes / bandwidth_bytes_per_sec
        ideal_time_us = ideal_time_sec * 1e6

        return ideal_time_us

    except Exception as e:
        print(f"Warning: Failed to calculate ideal JCT from {msg_sizes_file}: {e}")
        return None

def extract_pattern_from_filename(filename):
    """Extract traffic pattern from filename or config_id"""
    filename_lower = filename.lower()
    if "uniform" in filename_lower:
        return "uniform"
    elif "zipfian" in filename_lower or "zipf" in filename_lower:
        return "zipfian"
    elif "moe" in filename_lower:
        return "moe"
    elif "power2" in filename_lower:
        return "power2"
    elif "linear" in filename_lower:
        return "linear"
    elif "random" in filename_lower:
        return "random"
    else:
        return "unknown"  # Changed from "uniform" to "unknown"

def get_window_size_name(window_size):
    """Convert window size to descriptive name"""
    try:
        ws = int(window_size)
        if ws == 0:
            return "Unlimited"
        elif ws >= 1000000:
            return f"{ws//1000000}M"
        elif ws >= 1000:
            return f"{ws//1000}K"
        else:
            return str(ws)
    except (ValueError, TypeError):
        return str(window_size)

def get_message_size_name(message_size):
    """Convert message size to descriptive name"""
    try:
        ms = int(message_size)
        if ms >= 1048576:  # 1MB
            return f"{ms//1048576}MB"
        elif ms >= 1024:  # 1KB
            return f"{ms//1024}KB"
        else:
            return f"{ms}B"
    except (ValueError, TypeError):
        return str(message_size)

def get_group_size_name(group_size):
    """Convert group size to descriptive name"""
    try:
        gs = int(group_size)
        return f"{gs}nodes"
    except (ValueError, TypeError):
        return str(group_size)

def extract_bandwidth_from_topology(topology_name, default_bw=100):
    """Extract link bandwidth in Gbps from topology name (e.g., '400G' -> 400)."""
    import re
    m = re.search(r'(\d+)G', topology_name)
    if m:
        return int(m.group(1))
    return default_bw

def get_ranked_jct_data(filename, time_start, time_end):
    """
    Processes a raw JCT data file to get average JCT for each group rank.
    The logic is modeled after the analysis in the provided JCT plotting script.

    Args:
        filename (str): Path to the raw JCT output file (e.g., '..._out_jct.txt').
        time_start (int): The start time (in ns) for filtering records.
        time_end (int): The end time (in ns) for filtering records.

    Returns:
        dict: A dictionary containing sorted ranks and their corresponding average JCTs in microseconds,
              or None if processing fails or yields no data.
    """
    # This awk command filters records by time and extracts the round ID ($1) and JCT in ns ($4)
    cmd_get_raw = f"cat {filename} | awk '{{ if ($3 > {time_start} && ($3 + $4) < {time_end}) print $1, $4}}'"
    jcts_by_round = defaultdict(list)
    try:
        output_raw = subprocess.check_output(cmd_get_raw, shell=True).decode("utf-8")
        if not output_raw.strip():
            print(f"Warning: No data returned from command for {filename}.")
            return None

        for line in output_raw.strip().split('\n'):
            parts = line.split()
            round_id = int(parts[0])
            jct_ns = float(parts[1])
            # Convert JCT from nanoseconds to microseconds
            jcts_by_round[round_id].append(jct_ns / 1000.0)

    except (subprocess.CalledProcessError, ValueError, IndexError) as e:
        print(f"Warning: Command or parsing failed for {filename}. Error: {e}. Returning None.")
        return None

    if not jcts_by_round:
        return None

    # Group JCTs by their rank within each round
    jcts_by_rank = defaultdict(list)
    for round_id, jct_list in jcts_by_round.items():
        sorted_jcts = sorted(jct_list)
        for rank, jct_value in enumerate(sorted_jcts):
            jcts_by_rank[rank].append(jct_value)

    # Calculate the average JCT for each rank across all rounds
    avg_jct_by_rank = {rank: np.mean(jct_values) for rank, jct_values in jcts_by_rank.items()}

    if not avg_jct_by_rank:
        return None

    sorted_ranks = sorted(avg_jct_by_rank.keys())
    avg_jcts = [avg_jct_by_rank[r] for r in sorted_ranks]

    # Infer group size from the number of flows per round
    inferred_group_size = max(len(jct_list) for jct_list in jcts_by_round.values())

    return {"ranks": sorted_ranks, "avg_jcts_us": avg_jcts, "group_size": inferred_group_size}

def calculate_ideal_jct_for_workload(workload, pattern, message_size, topology="fat_k8_100G_OS1", group_size=8):
    """
    Calculate ideal JCT using appropriate analyzer based on workload type

    Args:
        workload: Workload type (e.g., "AlltoallV", "Alltoall", "RingAllreduce", "TreeAllreduce")
        pattern: Traffic pattern (e.g., "uniform", "zipfian", "moe")
        message_size: Message size in bytes
        topology: Topology name
        group_size: Group size

    Returns:
        ideal_jct_us: Ideal JCT in microseconds, or None if calculation fails
    """
    if not AlltoallVAnalyzer or not TreeAllReduceAnalyzer or not NetworkTopology:
        print("Warning: optimal_jct_analyzer not available. Cannot calculate ideal JCT.")
        return None

    try:
        # Initialize network topology
        topo = NetworkTopology(topology)

        if workload in ["AlltoallV", "Alltoall"]:
            # Use AlltoallV analyzer
            analyzer = AlltoallVAnalyzer(topo)

            # Map workload to pattern
            if workload == "AlltoallV":
                analysis_pattern = pattern
            else:
                analysis_pattern = "uniform"  # Traditional alltoall is uniform

            # Generate traffic matrix and calculate ideal JCT
            traffic_matrix = analyzer.generate_traffic_matrix(analysis_pattern, message_size, group_size)
            results = analyzer.calculate_optimal_jct(traffic_matrix, analysis_pattern)
            ideal_jct_us = results['ideal_jct_ms'] * 1000  # Convert ms to μs

        elif workload in ["RingAllreduce", "TreeAllreduce"]:
            # Use Tree AllReduce analyzer (works for both ring and tree)
            analyzer = TreeAllReduceAnalyzer(topo)
            results = analyzer.calculate_tree_allreduce_jct(message_size, group_size)
            ideal_jct_us = results['optimal_jct_ms'] * 1000  # Convert ms to μs

        else:
            print(f"Warning: Unknown workload type {workload}, cannot calculate ideal JCT")
            return None

        print(f"Calculated ideal JCT for {workload} ({pattern}): {ideal_jct_us:.2f} μs")
        return ideal_jct_us

    except Exception as e:
        print(f"Warning: Failed to calculate ideal JCT for {workload} {pattern}: {e}")
        return None

def main():
    """
    Main function to parse a history file, process corresponding JCT data,
    calculate ideal JCT for each group, and save the aggregated results into JSON files.
    """
    parser = argparse.ArgumentParser(description='Parse JCT results with ideal JCT calculation into JSON files for plotting.')
    parser.add_argument('history_file', type=str, help='Path to the classified history file to parse.')
    parser.add_argument('-sT', dest='time_limit_begin', type=int, default=0, help='Start time in ns for filtering.')
    parser.add_argument('-fT', dest='time_limit_end', type=int, default=10000000000000000000, help='End time in ns for filtering.')
    parser.add_argument('--group_size', type=int, default=8, help='Group size for ideal JCT calculation')
    parser.add_argument('--topology', type=str, default='fat_k8_100G_OS1', help='Topology name for ideal JCT calculation')
    parser.add_argument('--bandwidth', type=int, default=100, help='Link bandwidth in Gbps for ideal JCT calculation')
    parser.add_argument('--merge-timeout', action='store_true', help='Merge results with different timeout modes into the same JSON file')
    parser.add_argument('--merge-cc', action='store_true', help='Merge results with different CC modes into the same JSON file (CC mode becomes a series dimension)')
    parser.add_argument('--mode', choices=['per_group', 'vs_groupsize'], default='per_group',
                        help='Output mode: per_group (one JSON per group size, existing behavior) or '
                             'vs_groupsize (one JSON per config with group size as x-axis)')
    args = parser.parse_args()

    file_dir = get_file_path()
    output_dir = os.path.join(file_dir, "../mix/output")

    history_filename = args.history_file
    print(f"Processing history file: {history_filename}")

    # A dictionary to group experiments by common parameters
    map_key_to_id = defaultdict(list)
    workload_pattern_by_group = {}  # Store workload and pattern info for each group

    with open(history_filename, "r") as f:
        for line in f.readlines():
            if ',' not in line:
                continue

            parsed = line.strip().split(',')
            if len(parsed) < 22:
                continue

            try:
                # Parsing based on the format inferred from the provided plotting script
                config_id = parsed[1]
                cc_mode_id = int(parsed[2])
                lb_mode_id = int(parsed[3])
                ar_mode = parsed[4]
                pfc = int(parsed[10])
                irn = int(parsed[11])
                window_size = parsed[14]
                topo = parsed[15]
                load_type = parsed[17]
                message_size = parsed[18]
                error_rate = parsed[19]
                timeout_mode = parsed[21]

                # Skip configurations with undefined modes
                if (cc_mode_id not in cc_modes or
                    lb_mode_id not in lb_modes or
                    irn not in irn_modes):
                    continue

                # Extract traffic pattern for AlltoallV workloads, and read per-entry group_size
                if load_type == "AlltoallV":
                    # First check the message sizes filename for pattern
                    msg_sizes_file = f"{output_dir}/{config_id}/{config_id}_alltoallv_msg_sizes.txt"
                    pattern = extract_pattern_from_message_sizes_filename(msg_sizes_file)
                    # If not found, try config_id
                    if pattern == "unknown":
                        pattern = extract_pattern_from_filename(config_id)
                    # Default to zipfian if still unknown (based on data structure)
                    if pattern == "unknown":
                        pattern = "zipfian"
                    # Read group_size directly from this entry's message sizes file
                    entry_group_size = get_group_size_from_message_sizes(msg_sizes_file)
                    if entry_group_size is None:
                        entry_group_size = args.group_size
                else:
                    pattern = "uniform"  # Default for other workloads
                    entry_group_size = args.group_size  # Fallback; JCT-based detection done later

                # Determine human-readable labels for modes
                cc_label = cc_names.get(cc_modes.get(cc_mode_id), cc_modes.get(cc_mode_id, "unknown"))
                lb_label = lb_modes.get(lb_mode_id)
                recovery_label = irn_modes.get(irn)
                if ar_mode == '1':
                    if irn in (0, 1):
                        recovery_label = "RTO+GBN"
                    elif irn == 2:
                        recovery_label = "IdealTrimming"

                if timeout_mode == '1':
                    if recovery_label == "RTO+GBN":
                        recovery_label = "RTO+GBN+slowstart"
                    elif recovery_label == "IdealTrimming":
                        recovery_label = "IdealTrimming+slowstart"
                    elif recovery_label == "Ideal":
                        recovery_label = "Ideal+slowstart"

                if timeout_mode == '2':
                    if recovery_label == "RTO+GBN":
                        recovery_label = "RTO+GBN+1/2"
                    elif recovery_label == "IdealTrimming":
                        recovery_label = "IdealTrimming+1/2"

                flow_control = "Lossless" if pfc == 1 else "Lossy"

                # Build file-level grouping key.
                # --merge-cc:      cc_label -> "ALL_CC"  (CC mode becomes a series dimension)
                # --merge-timeout: timeout_mode -> "ALL"
                key_cc = "ALL_CC" if args.merge_cc else cc_label
                key_tmt = "ALL" if args.merge_timeout else timeout_mode

                # In vs_groupsize mode, group_size is excluded from the file-level key
                # and becomes the x-axis dimension inside each JSON.
                if args.mode == 'vs_groupsize':
                    key = (topo, load_type, pattern, key_cc, message_size, window_size, error_rate, key_tmt, flow_control)
                else:
                    # per_group mode: include group_size in key (original behavior)
                    key = (topo, load_type, pattern, key_cc, message_size, window_size, error_rate, key_tmt, flow_control, entry_group_size)

                # Store workload and pattern info for this group
                workload_pattern_by_group[key] = (load_type, pattern)

                entry_details = {
                    "config_id": config_id,
                    "cc_mode": cc_label,
                    "lb_mode": lb_label,
                    "recovery": recovery_label,
                    "timeout": timeout_mode,
                    "window": window_size,
                    "window_name": get_window_size_name(window_size),
                    "message_size": message_size,
                    "message_size_name": get_message_size_name(message_size),
                    "group_size": entry_group_size,
                    "group_size_name": get_group_size_name(entry_group_size),
                    "merge_cc": args.merge_cc,
                }
                map_key_to_id[key].append(entry_details)

            except (ValueError, IndexError) as e:
                print(f"Skipping malformed line in history file: {line.strip()} | Error: {e}")
                continue

    if args.mode == 'vs_groupsize':
        _process_vs_groupsize(map_key_to_id, workload_pattern_by_group, args, file_dir, output_dir)
    else:
        _process_per_group(map_key_to_id, workload_pattern_by_group, args, file_dir, output_dir)


def _process_per_group(map_key_to_id, workload_pattern_by_group, args, file_dir, output_dir):
    """Original mode: one JSON file per group size."""
    json_dir = os.path.join(file_dir, "json-data-jct-with-ideal/")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    for k, v in map_key_to_id.items():
        workload, pattern = workload_pattern_by_group.get(k, ("Unknown", "uniform"))
        effective_group_size = k[9]
        effective_topology = k[0]

        plot_group_data = {
            "metadata": {
                "topology": k[0],
                "load_type": k[1],
                "workload_pattern": k[2],
                "cc_mode": k[3],
                "message_size": k[4],
                "message_size_name": get_message_size_name(k[4]),
                "window_size": k[5],
                "window_size_name": get_window_size_name(k[5]),
                "error_rate": k[6],
                "timeout_mode": k[7],
                "flow_control": k[8],
                "group_size": effective_group_size,
                "group_size_name": get_group_size_name(effective_group_size),
                "merged_timeout": args.merge_timeout,
            },
            "data_series": [],
            "ideal_jct_data": {}
        }

        message_sizes_in_group = set(int(e["message_size"]) for e in v)

        if workload == "AlltoallV":
            if v:
                sample_config_id = v[0]["config_id"]
                msg_sizes_file = f"{output_dir}/{sample_config_id}/{sample_config_id}_alltoallv_msg_sizes.txt"
                print(f"Group size={effective_group_size}: computing ideal JCT from {msg_sizes_file}")
                bw = extract_bandwidth_from_topology(effective_topology, args.bandwidth)
                ideal_jct_us = calculate_ideal_jct_from_message_sizes(msg_sizes_file, bw)
                if ideal_jct_us is not None:
                    plot_group_data["ideal_jct_data"]["calculated"] = {
                        "ideal_jct_us": ideal_jct_us,
                        "workload": workload,
                        "pattern": pattern,
                        "method": "message_sizes_file",
                        "bandwidth_gbps": args.bandwidth
                    }
                    print(f"  Ideal JCT = {ideal_jct_us:.2f} μs")
        else:
            for msg_size in message_sizes_in_group:
                ideal_jct_us = calculate_ideal_jct_for_workload(
                    workload, pattern, msg_size, effective_topology, effective_group_size
                )
                if ideal_jct_us is not None:
                    plot_group_data["ideal_jct_data"][str(msg_size)] = {
                        "ideal_jct_us": ideal_jct_us,
                        "workload": workload,
                        "pattern": pattern
                    }

        for entry in v:
            config_id = entry["config_id"]
            jct_file = f"{output_dir}/{config_id}/{config_id}_out_jct.txt"
            if os.path.exists(jct_file):
                result = get_ranked_jct_data(jct_file, args.time_limit_begin, args.time_limit_end)
                if result:
                    series_data = {
                        "load_balancing_mode": entry["lb_mode"],
                        "congestion_control": entry["cc_mode"],
                        "recovery_mechanism": entry["recovery"],
                        "timeout_mode": entry["timeout"],
                        "window_size": entry["window"],
                        "window_size_name": entry["window_name"],
                        "message_size_bytes": int(entry["message_size"]),
                        "message_size_name": entry["message_size_name"],
                        "group_size": effective_group_size,
                        "group_size_name": get_group_size_name(effective_group_size),
                        "ranks": result["ranks"],
                        "avg_jct_us": result["avg_jcts_us"]
                    }
                    plot_group_data["data_series"].append(series_data)

        if not plot_group_data["data_series"]:
            print(f"Skipping group {k} due to no valid JCT data.")
            continue

        msg_size_name = get_message_size_name(k[4])
        win_size_name = get_window_size_name(k[5])
        grp_size_name = get_group_size_name(effective_group_size)
        json_filename = (f"{json_dir}/JCT_WITH_IDEAL_"
                        f"TOPO_{k[0]}_"
                        f"TYPE_{k[1]}_"
                        f"PATTERN_{k[2].upper()}_"
                        f"CC_{k[3]}_"
                        f"MSG_{msg_size_name}_"
                        f"WIN_{win_size_name}_"
                        f"ERR_{k[6]}_"
                        f"TMT_{k[7]}_"
                        f"FC_{k[8]}_"
                        f"GRP_{grp_size_name}.json")

        print(f"Saving data with ideal JCT to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(plot_group_data, f, indent=4)

        print(f"  Group summary: {workload} ({pattern})")
        for msg_size, ideal_data in plot_group_data["ideal_jct_data"].items():
            print(f"    Message size {msg_size}: Ideal JCT = {ideal_data['ideal_jct_us']:.2f} μs")

    print(f"\nCompleted! JSON files with ideal JCT saved in: {json_dir}")


def _process_vs_groupsize(map_key_to_id, workload_pattern_by_group, args, file_dir, output_dir):
    """
    vs_groupsize mode: one JSON per config, with group size as the x-axis.
    Each data series corresponds to a (lb_mode, recovery_mechanism) combination,
    and contains a list of points sorted by group_size.
    jct_us per point is the mean across all ranks (average JCT of the collective).
    """
    json_dir = os.path.join(file_dir, "json-data-jct-vs-groupsize/test-trim/")
    if not os.path.exists(json_dir):
        os.makedirs(json_dir)

    for k, v in map_key_to_id.items():
        workload, pattern = workload_pattern_by_group.get(k, ("Unknown", "uniform"))
        effective_topology = k[0]

        # Collect ideal JCT per group_size (keyed by group_size int)
        ideal_jct_by_groupsize = {}

        # Accumulate series points: series_key -> list of point dicts
        # series_key = (lb_mode, recovery_mechanism, timeout_mode)
        series_map = defaultdict(list)

        for entry in v:
            config_id = entry["config_id"]
            group_size = entry["group_size"]
            jct_file = f"{output_dir}/{config_id}/{config_id}_out_jct.txt"

            if not os.path.exists(jct_file):
                continue

            result = get_ranked_jct_data(jct_file, args.time_limit_begin, args.time_limit_end)
            if not result:
                continue

            avg_jcts = result["avg_jcts_us"]
            mean_jct_us = float(np.mean(avg_jcts))

            # Calculate ideal JCT for this group_size if not already done
            if group_size not in ideal_jct_by_groupsize:
                if workload == "AlltoallV":
                    msg_sizes_file = f"{output_dir}/{config_id}/{config_id}_alltoallv_msg_sizes.txt"
                    print(f"Group size={group_size}: computing ideal JCT from {msg_sizes_file}")
                    bw = extract_bandwidth_from_topology(effective_topology, args.bandwidth)
                    ideal_jct_us = calculate_ideal_jct_from_message_sizes(msg_sizes_file, bw)
                else:
                    ideal_jct_us = calculate_ideal_jct_for_workload(
                        workload, pattern, int(entry["message_size"]), effective_topology, group_size
                    )
                ideal_jct_by_groupsize[group_size] = ideal_jct_us
                if ideal_jct_us is not None:
                    print(f"  Ideal JCT = {ideal_jct_us:.2f} μs")

            merge_cc = entry.get("merge_cc", False)
            series_key = (entry["lb_mode"], entry["recovery"], entry["timeout"],
                          entry["cc_mode"] if merge_cc else "")
            point = {
                "group_size": group_size,
                "group_size_name": entry["group_size_name"],
                "jct_us": mean_jct_us,
                "all_ranks_jct_us": avg_jcts,
                "ideal_jct_us": ideal_jct_by_groupsize.get(group_size)
            }
            series_map[series_key].append(point)

        if not series_map:
            print(f"Skipping group {k} due to no valid JCT data.")
            continue

        # Build data_series list, sorting points within each series by group_size
        merge_cc = args.merge_cc
        data_series = []
        for (lb_mode, recovery, timeout_mode, cc_mode), points in series_map.items():
            points_sorted = sorted(points, key=lambda p: p["group_size"])
            label = f"{lb_mode} / {recovery}"
            series_entry = {
                "load_balancing_mode": lb_mode,
                "recovery_mechanism": recovery,
                "timeout_mode": timeout_mode,
                "congestion_control": cc_mode,
                "label": label,
                "points": points_sorted,
            }
            data_series.append(series_entry)
        # Sort series by label for consistent ordering
        data_series.sort(key=lambda s: s["label"])

        plot_group_data = {
            "metadata": {
                "topology": k[0],
                "load_type": k[1],
                "workload_pattern": k[2],
                "cc_mode": k[3],
                "message_size": k[4],
                "message_size_name": get_message_size_name(k[4]),
                "window_size": k[5],
                "window_size_name": get_window_size_name(k[5]),
                "error_rate": k[6],
                "timeout_mode": k[7],
                "flow_control": k[8],
                "x_axis": "group_size",
                "y_metric": "mean_rank_jct_us",
                "merged_timeout": args.merge_timeout,
            },
            "data_series": data_series
        }

        msg_size_name = get_message_size_name(k[4])
        win_size_name = get_window_size_name(k[5])
        json_filename = (f"{json_dir}/JCT_VS_GROUPSIZE_"
                        f"TOPO_{k[0]}_"
                        f"TYPE_{k[1]}_"
                        f"PATTERN_{k[2].upper()}_"
                        f"CC_{k[3]}_"
                        f"MSG_{msg_size_name}_"
                        f"WIN_{win_size_name}_"
                        f"ERR_{k[6]}_"
                        f"TMT_{k[7]}_"
                        f"FC_{k[8]}.json")

        print(f"Saving vs-groupsize data to: {json_filename}")
        with open(json_filename, 'w') as f:
            json.dump(plot_group_data, f, indent=4)

    print(f"\nCompleted! JSON files saved in: {json_dir}")

if __name__ == "__main__":
    main()