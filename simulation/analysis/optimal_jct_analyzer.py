#!/usr/bin/env python3
"""
Optimal JCT Analyzer for AlltoallV Traffic Patterns

Calculates theoretical optimal Job Completion Time (JCT) for different
AlltoallV traffic patterns considering network topology constraints.
"""

import numpy as np
import sys
import os
import re
from typing import Dict, List, Tuple, Optional

# Add parent directory to path to import run.py functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run import generate_zipfian_distribution

class NetworkTopology:
    """Network topology parser and analyzer"""

    def __init__(self, topo_file: str):
        self.topo_file = topo_file
        self.switches = {}
        self.servers = {}
        self.links = {}
        self.server_to_leaf = {}
        self.parse_topology()

    def parse_topology(self):
        """Parse NS-3 topology file"""
        try:
            with open(f"config/{self.topo_file}.txt", 'r') as f:
                content = f.read()

            # Extract number of servers and switches
            server_match = re.search(r'(\d+)\s+#servers', content)
            switch_match = re.search(r'(\d+)\s+#switches', content)

            if server_match and switch_match:
                self.num_servers = int(server_match.group(1))
                self.num_switches = int(switch_match.group(1))

            # Parse links to understand topology structure
            lines = content.split('\n')
            for line in lines:
                if re.match(r'^\d+\s+\d+\s+\d+', line):
                    parts = line.split()
                    if len(parts) >= 3:
                        src, dst, bw = int(parts[0]), int(parts[1]), int(parts[2])
                        self.links[(src, dst)] = {'bandwidth': bw}

            # Determine topology type and structure
            self.analyze_topology_structure()

        except FileNotFoundError:
            print(f"Warning: Could not find topology file: {self.topo_file}")
            # Use default values for known topologies
            self.set_default_topology_params()

    def analyze_topology_structure(self):
        """Analyze topology structure to identify fat-tree or leaf-spine"""
        if "fat_k8" in self.topo_file:
            self.topology_type = "fat_tree"
            self.k = 8
            self.num_pods = self.k
            self.servers_per_leaf = self.k // 2
            self.leaves_per_pod = self.k // 2
        elif "leaf_spine" in self.topo_file:
            self.topology_type = "leaf_spine"
            # Extract parameters from filename
            match = re.search(r'L(\d+)_S(\d+)', self.topo_file)
            if match:
                self.num_leaves = int(match.group(1))
                self.num_spines = int(match.group(2))
                self.servers_per_leaf = 8  # Common configuration
        else:
            self.topology_type = "unknown"

    def set_default_topology_params(self):
        """Set default parameters for known topologies"""
        if "fat_k8" in self.topo_file:
            self.topology_type = "fat_tree"
            self.k = 8
            self.num_servers = 128
            self.servers_per_leaf = 8
            self.server_link_bw = 100  # Gbps
        elif "leaf_spine_L8_S16" in self.topo_file:
            self.topology_type = "leaf_spine"
            self.num_servers = 128
            self.servers_per_leaf = 8
            self.server_link_bw = 100  # Gbps

    def get_bottleneck_bandwidth(self) -> float:
        """Calculate effective bottleneck bandwidth per server"""
        if self.topology_type == "fat_tree":
            # In fat-tree, server has 1 uplink, but multiple paths through fabric
            # Effective bandwidth depends on traffic pattern and load balancing
            return self.server_link_bw  # Conservative estimate: server uplink is bottleneck
        elif self.topology_type == "leaf_spine":
            # In leaf-spine, server has 1 uplink to leaf switch
            return self.server_link_bw
        else:
            return 100  # Default assumption

class TreeAllReduceAnalyzer:
    """Analyzer for Tree AllReduce traffic patterns"""

    def __init__(self, topology: NetworkTopology):
        self.topology = topology

    def build_binary_tree(self, group_size: int) -> Dict:
        """Build binary tree structure for group"""

        tree = {
            'nodes': {},
            'levels': [],
            'root_id': 0,
            'tree_height': 0
        }

        # Build complete binary tree (bottom-up)
        # Level 0 = leaves, highest level = root
        nodes_at_level = {}
        level = 0
        remaining_nodes = list(range(group_size))

        # Build tree level by level
        while len(remaining_nodes) > 1:
            nodes_at_level[level] = remaining_nodes.copy()

            # Parent level nodes
            parent_level_nodes = []
            for i in range(0, len(remaining_nodes), 2):
                left_child = remaining_nodes[i]
                right_child = remaining_nodes[i + 1] if i + 1 < len(remaining_nodes) else None

                # Find next available parent node ID
                parent_id = max(tree['nodes'].keys()) + 1 if tree['nodes'] else group_size

                # Create parent node
                tree['nodes'][parent_id] = {
                    'level': level + 1,
                    'children': [left_child] + ([right_child] if right_child is not None else []),
                    'parent': None,
                    'is_leaf': False,
                    'is_root': False
                }

                # Set children's parent
                tree['nodes'][left_child] = tree['nodes'].get(left_child, {
                    'level': level,
                    'children': [],
                    'parent': parent_id,
                    'is_leaf': True,
                    'is_root': False
                })
                tree['nodes'][left_child]['parent'] = parent_id

                if right_child is not None:
                    tree['nodes'][right_child] = tree['nodes'].get(right_child, {
                        'level': level,
                        'children': [],
                        'parent': parent_id,
                        'is_leaf': True,
                        'is_root': False
                    })
                    tree['nodes'][right_child]['parent'] = parent_id

                parent_level_nodes.append(parent_id)

            remaining_nodes = parent_level_nodes
            level += 1

        # Set root
        if remaining_nodes:
            tree['root_id'] = remaining_nodes[0]
            tree['nodes'][tree['root_id']]['is_root'] = True
            tree['tree_height'] = level

        # Set levels
        tree['levels'] = nodes_at_level

        return tree

    def calculate_tree_allreduce_jct(self, message_size: int, group_size: int) -> Dict:
        """Calculate optimal JCT for Tree AllReduce"""

        # Build tree structure
        tree = self.build_binary_tree(group_size)
        server_bw = self.topology.get_bottleneck_bandwidth()  # Gbps
        server_bw_bps = server_bw * 1e9  # Convert to bps

        # Calculate transmission time for message_size
        transmission_time_sec = message_size * 8 / server_bw_bps

        results = {
            'algorithm': 'tree_allreduce',
            'group_size': group_size,
            'message_size': message_size,
            'server_bandwidth_gbps': server_bw,
            'tree_height': tree['tree_height'],
            'transmission_time_sec': transmission_time_sec,
        }

        # Tree AllReduce has two phases:
        # 1. Reduce phase: leaves -> root (tree_height steps)
        # 2. Broadcast phase: root -> leaves (tree_height steps)

        reduce_phase_time = tree['tree_height'] * transmission_time_sec
        broadcast_phase_time = tree['tree_height'] * transmission_time_sec

        # Total time is sequential: reduce + broadcast
        total_time_sec = reduce_phase_time + broadcast_phase_time

        # Add some congestion penalty for practical networks
        congestion_factor = 1.1  # Small penalty since tree has good load distribution
        optimal_jct_sec = total_time_sec * congestion_factor

        results.update({
            'reduce_phase_time_sec': reduce_phase_time,
            'broadcast_phase_time_sec': broadcast_phase_time,
            'ideal_jct_sec': total_time_sec,
            'ideal_jct_ms': total_time_sec * 1000,
            'optimal_jct_sec': optimal_jct_sec,
            'optimal_jct_ms': optimal_jct_sec * 1000,
            'tree_structure': tree,
            'bottleneck_type': 'sequential_phases'
        })

        return results

class AlltoallVAnalyzer:
    """Analyzer for AlltoallV traffic patterns"""

    def __init__(self, topology: NetworkTopology):
        self.topology = topology

    def load_message_sizes_from_file(self, filepath: str) -> Tuple[List[List[int]], List[np.ndarray]]:
        """Load message sizes from run.py generated file

        Returns:
            groups: List of group node IDs
            traffic_matrices: List of traffic matrices per group
        """
        groups = []
        group_matrices = {}

        print(f"Loading message sizes from: {filepath}")

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue

                    parts = line.split()
                    if len(parts) != 4:
                        continue

                    group_id, src_idx, dst_idx, size = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])

                    # Initialize group matrix if needed
                    if group_id not in group_matrices:
                        # Need to determine group size first
                        group_matrices[group_id] = {}

                    group_matrices[group_id][(src_idx, dst_idx)] = size

        except FileNotFoundError:
            raise FileNotFoundError(f"Message sizes file not found: {filepath}")
        except Exception as e:
            raise ValueError(f"Error parsing message sizes file: {e}")

        # Convert to numpy matrices
        traffic_matrices = []
        group_list = []

        for group_id in sorted(group_matrices.keys()):
            entries = group_matrices[group_id]

            # Determine group size
            max_idx = max(max(src_idx, dst_idx) for src_idx, dst_idx in entries.keys())
            group_size = max_idx + 1

            # Create traffic matrix
            matrix = np.zeros((group_size, group_size), dtype=np.int64)
            for (src_idx, dst_idx), size in entries.items():
                matrix[src_idx, dst_idx] = size

            traffic_matrices.append(matrix)
            # Create dummy group (node IDs don't matter for analysis)
            group_list.append(list(range(group_size)))

        print(f"Loaded {len(traffic_matrices)} groups with sizes: {[m.shape[0] for m in traffic_matrices]}")
        return group_list, traffic_matrices

    def generate_traffic_matrix(self, pattern: str, base_size: int, group_size: int) -> np.ndarray:
        """Generate traffic matrix for given pattern"""

        if pattern == "uniform":
            # Mode 1: Uniform distribution
            # base_size is now the average message size per flow
            matrix = np.full((group_size, group_size), base_size)
            np.fill_diagonal(matrix, 0)  # No self-communication

        elif pattern == "zipfian":
            # Mode 2: Zipfian flow-level distribution
            # base_size is now the average message size per flow
            alpha = 0.8
            zipf_weights = generate_zipfian_distribution(group_size - 1, alpha)

            matrix = np.zeros((group_size, group_size))
            for src in range(group_size):
                weight_idx = 0
                for dst in range(group_size):
                    if src != dst:
                        # Scale Zipfian weights to have average = base_size
                        matrix[src, dst] = base_size * zipf_weights[weight_idx] * (group_size - 1)
                        weight_idx += 1

        elif pattern == "moe":
            # Mode 3: MoE incast pattern
            # base_size is now the average message size per flow
            alpha = 0.8
            receiver_weights = generate_zipfian_distribution(group_size, alpha)

            # Total system traffic (base_size is average flow size)
            total_traffic = base_size * group_size * (group_size - 1)
            receiver_capacities = receiver_weights * total_traffic

            # Each sender capacity (sends to group_size-1 others)
            sender_capacity = base_size * (group_size - 1)

            # Initialize uniform from each sender (use float for calculations)
            matrix = np.full((group_size, group_size), float(base_size))
            np.fill_diagonal(matrix, 0)

            # Iterative scaling to satisfy receiver constraints
            for iteration in range(100):
                # Adjust for receiver constraints
                for dst in range(group_size):
                    current_received = np.sum(matrix[:, dst])
                    if current_received > 0:
                        scale_factor = receiver_capacities[dst] / current_received
                        matrix[:, dst] *= scale_factor
                        matrix[dst, dst] = 0

                # Re-normalize sender constraints
                for src in range(group_size):
                    current_sent = np.sum(matrix[src, :])
                    if current_sent > 0:
                        scale_factor = sender_capacity / current_sent
                        matrix[src, :] *= scale_factor
                        matrix[src, src] = 0

        else:
            raise ValueError(f"Unknown pattern: {pattern}")

        return matrix.astype(np.int64)

    def calculate_optimal_jct(self, traffic_matrix: np.ndarray, pattern: str) -> Dict:
        """Calculate optimal JCT considering network constraints"""

        group_size = traffic_matrix.shape[0]
        server_bw = self.topology.get_bottleneck_bandwidth()  # Gbps
        server_bw_bps = server_bw * 1e9  # Convert to bps

        # Analysis results
        results = {
            'pattern': pattern,
            'group_size': group_size,
            'server_bandwidth_gbps': server_bw,
            'traffic_matrix': traffic_matrix
        }

        # Calculate per-server loads
        sender_loads = np.sum(traffic_matrix, axis=1)  # Total bytes sent by each server
        receiver_loads = np.sum(traffic_matrix, axis=0)  # Total bytes received by each server

        # Calculate transmission times (ignoring network fabric for now)
        sender_times = sender_loads * 8 / server_bw_bps  # Time to send all data
        receiver_times = receiver_loads * 8 / server_bw_bps  # Time to receive all data

        results.update({
            'sender_loads_bytes': sender_loads,
            'receiver_loads_bytes': receiver_loads,
            'sender_transmission_times_sec': sender_times,
            'receiver_transmission_times_sec': receiver_times,
            'max_sender_time_sec': np.max(sender_times),
            'max_receiver_time_sec': np.max(receiver_times),
        })

        # Simple bottleneck analysis
        # In practice, the JCT is limited by:
        # 1. Time for heaviest sender to transmit all data
        # 2. Time for heaviest receiver to receive all data
        # 3. Network fabric congestion (complex to model precisely)

        # Conservative estimate: max of sender and receiver bottlenecks
        ideal_jct_sec = max(np.max(sender_times), np.max(receiver_times))

        # Store ideal JCT (without network congestion penalties)
        optimal_jct_sec = ideal_jct_sec

        # Add network fabric delay estimate
        if pattern == "moe":
            # Incast pattern has additional congestion in fabric
            incast_penalty = 1.5  # Empirical factor for incast congestion
            optimal_jct_sec *= incast_penalty
        elif pattern == "zipfian":
            # Flow-level skew has some congestion but less than incast
            skew_penalty = 1.2
            optimal_jct_sec *= skew_penalty

        results.update({
            'ideal_jct_sec': ideal_jct_sec,
            'ideal_jct_ms': ideal_jct_sec * 1000,
            'optimal_jct_sec': optimal_jct_sec,
            'optimal_jct_ms': optimal_jct_sec * 1000,
            'bottleneck_type': 'sender' if np.max(sender_times) > np.max(receiver_times) else 'receiver'
        })

        return results

    def analyze_pattern_comparison(self, base_size: int, group_size: int) -> Dict:
        """Compare different traffic patterns"""

        patterns = ['uniform', 'zipfian', 'moe']
        comparison = {}

        for pattern in patterns:
            try:
                traffic_matrix = self.generate_traffic_matrix(pattern, base_size, group_size)
                results = self.calculate_optimal_jct(traffic_matrix, pattern)
                comparison[pattern] = results
            except Exception as e:
                print(f"Error analyzing pattern {pattern}: {e}")

        return comparison

    def analyze_from_history_id(self, history_id: str) -> Dict:
        """Analyze experiment results from history ID"""

        import os
        import re

        # Find config and output files
        config_path = f"mix/output/{history_id}/config.txt"
        jct_path = f"mix/output/{history_id}/{history_id}_out_jct.txt"
        msg_sizes_path = f"mix/output/{history_id}/{history_id}_alltoallv_msg_sizes.txt"

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        if not os.path.exists(jct_path):
            raise FileNotFoundError(f"JCT file not found: {jct_path}")

        # Parse experiment configuration
        config = self.parse_config_file(config_path)
        workload_type = config.get('workload_type', 'unknown')
        ai_message_size = int(config.get('ai_message_size', 0))
        topology = config.get('topology_file', 'unknown')

        print(f"Analyzing history ID: {history_id}")
        print(f"Workload type: {workload_type}")
        print(f"AI message size: {ai_message_size:,} bytes")
        print(f"Topology: {topology}")

        # Determine workload algorithm
        if workload_type == "1":  # Alltoall
            algorithm = "alltoall"
        elif workload_type == "2":  # RingAllreduce
            algorithm = "ring_allreduce"
        elif workload_type == "3":  # TreeAllreduce
            algorithm = "tree_allreduce"
        elif workload_type == "4":  # TreeAllreduceChunked
            algorithm = "tree_allreduce"
        elif workload_type == "5":  # AlltoallV
            algorithm = "alltoallv"
        else:
            algorithm = "unknown"

        print(f"Detected algorithm: {algorithm}")

        # Calculate optimal baseline
        baseline_results = self.calculate_baseline_for_algorithm(
            algorithm, ai_message_size, config)

        # Parse actual JCT results
        actual_jcts = self.parse_jct_file(jct_path)

        # Combine results
        results = {
            'history_id': history_id,
            'experiment_config': config,
            'algorithm': algorithm,
            'baseline': baseline_results,
            'actual_results': actual_jcts,
            'performance_ratio': {}
        }

        # Calculate performance ratios
        if actual_jcts and baseline_results:
            if 'optimal_jct_ms' in baseline_results:
                baseline_jct = baseline_results['optimal_jct_ms']
                for metric, value in actual_jcts.items():
                    if 'jct' in metric.lower() and isinstance(value, (int, float)):
                        results['performance_ratio'][metric] = value / baseline_jct

        return results

    def parse_config_file(self, config_path: str) -> Dict:
        """Parse NS-3 config.txt file"""

        config = {}
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Parse key-value pairs
                    parts = line.split(' ', 1)
                    if len(parts) >= 2:
                        key = parts[0].lower()
                        value = parts[1]
                        config[key] = value

        except Exception as e:
            print(f"Warning: Could not parse config file {config_path}: {e}")

        return config

    def parse_jct_file(self, jct_path: str) -> Dict:
        """Parse JCT output file and calculate statistics"""

        jcts = []
        try:
            with open(jct_path, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 4:  # round_id src_id start_time jct_ns
                        jct_ns = float(parts[3])
                        jcts.append(jct_ns / 1000000.0)  # Convert to ms

        except Exception as e:
            print(f"Warning: Could not parse JCT file {jct_path}: {e}")
            return {}

        if not jcts:
            return {}

        import numpy as np
        results = {
            'mean_jct_ms': np.mean(jcts),
            'median_jct_ms': np.median(jcts),
            'p95_jct_ms': np.percentile(jcts, 95),
            'p99_jct_ms': np.percentile(jcts, 99),
            'min_jct_ms': np.min(jcts),
            'max_jct_ms': np.max(jcts),
            'std_jct_ms': np.std(jcts),
            'total_flows': len(jcts)
        }

        return results

    def calculate_baseline_for_algorithm(self, algorithm: str, message_size: int, config: Dict) -> Dict:
        """Calculate baseline for specific algorithm"""

        # Extract group size from config (try to detect from topology or use default)
        group_size = 8  # Default

        topology_file = config.get('topology_file', '')
        if 'leaf_spine' in topology_file:
            # Try to extract from leaf-spine topology
            import re
            match = re.search(r'L(\d+)', topology_file)
            if match:
                num_leaves = int(match.group(1))
                group_size = min(8, num_leaves)  # Assume 8 servers per group max

        if algorithm == 'tree_allreduce':
            # Use TreeAllReduceAnalyzer
            tree_analyzer = TreeAllReduceAnalyzer(self.topology)
            return tree_analyzer.calculate_tree_allreduce_jct(message_size, group_size)

        elif algorithm in ['alltoallv', 'alltoall']:
            # Use AlltoallV analyzer with uniform pattern
            matrix = self.generate_traffic_matrix('uniform', message_size, group_size)
            return self.calculate_optimal_jct(matrix, 'uniform')

        elif algorithm == 'ring_allreduce':
            # TODO: Implement ring allreduce baseline
            return {'optimal_jct_ms': 0, 'note': 'Ring AllReduce baseline not implemented'}

        else:
            return {'error': f'Unknown algorithm: {algorithm}'}

    def analyze_from_file(self, filepath: str) -> Dict:
        """Analyze message sizes loaded from file"""

        groups, traffic_matrices = self.load_message_sizes_from_file(filepath)

        results = {}
        total_groups = len(traffic_matrices)

        print(f"\nAnalyzing {total_groups} groups from file...")

        for g, matrix in enumerate(traffic_matrices):
            group_size = matrix.shape[0]

            # Detect pattern type based on traffic distribution
            pattern = self.detect_pattern_type(matrix)

            print(f"\nGroup {g}: {group_size}x{group_size} matrix, detected pattern: {pattern}")

            # Calculate optimal JCT for this group
            group_results = self.calculate_optimal_jct(matrix, pattern)
            group_results['group_id'] = g
            group_results['group_size'] = group_size
            group_results['matrix_shape'] = matrix.shape

            results[f'group_{g}'] = group_results

            # Print summary for this group
            print(f"  Optimal JCT: {group_results['optimal_jct_ms']:.2f} ms")
            print(f"  Bottleneck: {group_results['bottleneck_type']}")
            print(f"  Sender load balance: {np.max(group_results['sender_loads_bytes'])/np.mean(group_results['sender_loads_bytes']):.2f}x")
            print(f"  Receiver load balance: {np.max(group_results['receiver_loads_bytes'])/np.mean(group_results['receiver_loads_bytes']):.2f}x")

        return results

    def detect_pattern_type(self, matrix: np.ndarray) -> str:
        """Detect traffic pattern type from matrix"""

        group_size = matrix.shape[0]

        # Check for uniform pattern (all non-diagonal elements equal)
        non_diag_elements = []
        for i in range(group_size):
            for j in range(group_size):
                if i != j and matrix[i, j] > 0:
                    non_diag_elements.append(matrix[i, j])

        if len(non_diag_elements) == 0:
            return "empty"

        # Check if all elements are (approximately) equal
        if len(set(non_diag_elements)) <= 2:  # Allow for small variations
            return "uniform"

        # Check coefficient of variation for sender/receiver loads
        sender_loads = np.sum(matrix, axis=1)
        receiver_loads = np.sum(matrix, axis=0)

        sender_cv = np.std(sender_loads) / np.mean(sender_loads) if np.mean(sender_loads) > 0 else 0
        receiver_cv = np.std(receiver_loads) / np.mean(receiver_loads) if np.mean(receiver_loads) > 0 else 0

        # If receivers are much more imbalanced than senders, likely MoE
        if receiver_cv > 2 * sender_cv and receiver_cv > 0.3:
            return "moe"
        # If both have significant variation, likely Zipfian
        elif sender_cv > 0.2 or receiver_cv > 0.2:
            return "zipfian"
        else:
            return "uniform"

def main():
    """Main analysis function"""
    import argparse

    parser = argparse.ArgumentParser(description='Analyze optimal JCT for AlltoallV patterns')
    parser.add_argument('--topo', default='fat_k8_100G_OS1', help='Topology name')
    parser.add_argument('--base_size', type=int, default=1048576, help='Base message size in bytes')
    parser.add_argument('--group_size', type=int, default=8, help='Group size (servers per group)')
    parser.add_argument('--pattern', default='all', help='Pattern to analyze: uniform/zipfian/moe/all')
    parser.add_argument('--file', type=str, help='Message sizes file from run.py to analyze')
    parser.add_argument('--output', type=str, help='Output file for results (optional)')
    parser.add_argument('--algorithm', default='alltoallv', help='Algorithm to analyze: alltoallv/tree_allreduce/ring_allreduce')
    parser.add_argument('--history_id', type=str, help='History ID to analyze (e.g., experiment output directory name)')
    parser.add_argument('--compare', action='store_true', help='Show performance comparison with baseline')

    args = parser.parse_args()

    # Initialize analyzer based on algorithm
    topology = NetworkTopology(args.topo)

    if args.algorithm == 'tree_allreduce':
        analyzer = TreeAllReduceAnalyzer(topology)
        print(f"=== Tree AllReduce Optimal JCT Analysis ===")
    elif args.algorithm == 'ring_allreduce':
        # TODO: Implement Ring AllReduce analyzer
        print("Ring AllReduce analyzer not implemented yet")
        return
    else:
        analyzer = AlltoallVAnalyzer(topology)
        print(f"=== AlltoallV Optimal JCT Analysis ===")

    print(f"Topology: {args.topo}")
    print(f"Server bandwidth: {topology.get_bottleneck_bandwidth()} Gbps")

    # Check if analyzing from history ID
    if args.history_id:
        print(f"History ID: {args.history_id}")
        print()

        # Analyze from history ID
        results = analyzer.analyze_from_history_id(args.history_id)

        # Print summary
        print(f"\n=== Baseline vs Actual Performance ===")
        baseline = results['baseline']
        actual = results['actual_results']

        if 'error' in baseline:
            print(f"Error calculating baseline: {baseline['error']}")
        elif actual:
            print(f"Baseline JCT: {baseline.get('optimal_jct_ms', 'N/A'):.2f} ms")
            print(f"Actual mean JCT: {actual.get('mean_jct_ms', 'N/A'):.2f} ms")
            print(f"Actual median JCT: {actual.get('median_jct_ms', 'N/A'):.2f} ms")
            print(f"Actual P95 JCT: {actual.get('p95_jct_ms', 'N/A'):.2f} ms")
            print(f"Actual P99 JCT: {actual.get('p99_jct_ms', 'N/A'):.2f} ms")
            print(f"Total flows: {actual.get('total_flows', 'N/A')}")

            # Performance ratios
            ratios = results['performance_ratio']
            if ratios:
                print(f"\nPerformance vs Baseline:")
                for metric, ratio in ratios.items():
                    print(f"  {metric}: {ratio:.2f}x baseline")
        else:
            print("No actual JCT data found")

        # Save results if output file specified
        if args.output:
            import json
            with open(args.output, 'w') as f:
                # Convert numpy types to native Python types
                def convert_numpy(obj):
                    if hasattr(obj, 'item'):
                        return obj.item()
                    elif hasattr(obj, 'tolist'):
                        return obj.tolist()
                    elif isinstance(obj, dict):
                        return {k: convert_numpy(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_numpy(v) for v in obj]
                    else:
                        return obj

                json.dump(convert_numpy(results), f, indent=2)
            print(f"\nResults saved to: {args.output}")

        return

    # Check if analyzing from file
    elif args.file:
        print(f"Input file: {args.file}")
        print()

        if args.algorithm == 'tree_allreduce':
            # Tree AllReduce doesn't use message size files, analyze directly
            print("Error: Tree AllReduce doesn't support message size files. Use --base_size instead.")
            return
        else:
            # Analyze from message sizes file (AlltoallV)
            results = analyzer.analyze_from_file(args.file)

            # Save results if output file specified
            if args.output:
                import json
                with open(args.output, 'w') as f:
                    # Convert numpy arrays to lists for JSON serialization
                    serializable_results = {}
                    for key, group_results in results.items():
                        serializable_results[key] = {}
                        for k, v in group_results.items():
                            if isinstance(v, np.ndarray):
                                serializable_results[key][k] = v.tolist()
                            else:
                                serializable_results[key][k] = v

                    json.dump(serializable_results, f, indent=2)
                print(f"\nResults saved to: {args.output}")

        return

    print(f"Base message size: {args.base_size:,} bytes ({args.base_size/1024/1024:.1f} MB)")
    print(f"Group size: {args.group_size} servers")
    print()

    if args.algorithm == 'tree_allreduce':
        # Analyze Tree AllReduce
        results = analyzer.calculate_tree_allreduce_jct(args.base_size, args.group_size)

        print("Tree AllReduce Analysis:")
        print("-" * 60)
        print(f"Tree height: {results['tree_height']} levels")
        print(f"Transmission time per hop: {results['transmission_time_sec']*1000:.2f} ms")
        print(f"Reduce phase time: {results['reduce_phase_time_sec']*1000:.2f} ms")
        print(f"Broadcast phase time: {results['broadcast_phase_time_sec']*1000:.2f} ms")
        print(f"Ideal JCT (no congestion): {results['ideal_jct_ms']:.2f} ms")
        print(f"Optimal JCT (with congestion): {results['optimal_jct_ms']:.2f} ms")
        print(f"Bottleneck: {results['bottleneck_type']}")

        # Show tree structure
        tree = results['tree_structure']
        print(f"\nTree Structure:")
        print(f"  Root node: {tree['root_id']}")
        print(f"  Levels: {tree['levels']}")

        # Save results if output file specified
        if args.output:
            import json
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to: {args.output}")

    elif args.pattern == 'all':
        # Compare all AlltoallV patterns
        comparison = analyzer.analyze_pattern_comparison(args.base_size, args.group_size)

        print("Pattern Comparison:")
        print("-" * 100)
        print(f"{'Pattern':<12} {'Max Sender (ms)':<15} {'Max Receiver (ms)':<17} {'Ideal JCT (ms)':<15} {'With Congestion (ms)':<18} {'Bottleneck':<12}")
        print("-" * 100)

        for pattern, results in comparison.items():
            print(f"{pattern:<12} "
                  f"{results['max_sender_time_sec']*1000:<15.2f} "
                  f"{results['max_receiver_time_sec']*1000:<17.2f} "
                  f"{results['ideal_jct_ms']:<15.2f} "
                  f"{results['optimal_jct_ms']:<18.2f} "
                  f"{results['bottleneck_type']:<12}")

        print()

        # Show traffic distribution details
        for pattern, results in comparison.items():
            print(f"\n{pattern.upper()} Pattern Details:")
            print(f"  Sender loads (MB): {results['sender_loads_bytes']/1024/1024}")
            print(f"  Receiver loads (MB): {results['receiver_loads_bytes']/1024/1024}")
            print(f"  Load balance factor (sender): {np.max(results['sender_loads_bytes'])/np.mean(results['sender_loads_bytes']):.2f}")
            print(f"  Load balance factor (receiver): {np.max(results['receiver_loads_bytes'])/np.mean(results['receiver_loads_bytes']):.2f}")

    else:
        # Analyze single AlltoallV pattern
        traffic_matrix = analyzer.generate_traffic_matrix(args.pattern, args.base_size, args.group_size)
        results = analyzer.calculate_optimal_jct(traffic_matrix, args.pattern)

        print(f"{args.pattern.upper()} Pattern Analysis:")
        print(f"  Ideal JCT (no congestion): {results['ideal_jct_ms']:.2f} ms")
        print(f"  With congestion penalties: {results['optimal_jct_ms']:.2f} ms")
        print(f"  Bottleneck: {results['bottleneck_type']}")
        print(f"  Max sender time: {results['max_sender_time_sec']*1000:.2f} ms")
        print(f"  Max receiver time: {results['max_receiver_time_sec']*1000:.2f} ms")

if __name__ == "__main__":
    main()