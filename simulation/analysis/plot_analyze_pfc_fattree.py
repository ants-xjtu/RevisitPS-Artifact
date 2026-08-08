#!/usr/bin/python3

import pandas as pd
import matplotlib.pyplot as plt
import argparse
import os
import numpy as np

# ===============================================================
# Fat-Tree Topology Definition
# ===============================================================
class FatTreeTopology:
    """
    Encapsulates the logic and parameters for a k-ary Fat-Tree topology.
    """
    def __init__(self, k=8):
        if k % 2 != 0:
            raise ValueError("k must be an even number for a standard Fat-Tree.")
        self.k = k
        self.num_pods = k
        
        self.ports_per_switch = k
        self.half_ports = k // 2

        self.num_core = (k // 2) ** 2
        self.num_aggr_per_pod = self.half_ports
        self.num_edge_per_pod = self.half_ports
        
        self.num_aggr = self.num_pods * self.num_aggr_per_pod
        self.num_edge = self.num_pods * self.num_edge_per_pod
        
        self.servers_per_edge = self.half_ports
        self.num_servers = self.num_edge * self.servers_per_edge

        # Define Node ID ranges
        self.id_offset_server = 0
        self.id_offset_edge = self.num_servers
        self.id_offset_aggr = self.id_offset_edge + self.num_edge
        self.id_offset_core = self.id_offset_aggr + self.num_aggr
        
        self.id_end_server = self.id_offset_edge - 1
        self.id_end_edge = self.id_offset_aggr - 1
        self.id_end_aggr = self.id_offset_core - 1
        self.id_end_core = self.id_offset_core + self.num_core - 1

    def get_node_type(self, node_id):
        """Returns the type of a node ('Server', 'Edge', 'Aggr', 'Core') based on its ID."""
        if self.id_offset_server <= node_id <= self.id_end_server:
            return 'Server'
        elif self.id_offset_edge <= node_id <= self.id_end_edge:
            return 'Edge'
        elif self.id_offset_aggr <= node_id <= self.id_end_aggr:
            return 'Aggr'
        elif self.id_offset_core <= node_id <= self.id_end_core:
            return 'Core'
        return 'Unknown'

    def get_port_type(self, row):
        """Determines the type of a port based on its node and interface index."""
        node_id = row['NodeID']
        if_index = row['IfIndex']
        node_type = self.get_node_type(node_id)
        
        if node_type == 'Edge':
            return 'Edge-to-Server' if if_index <= self.half_ports else 'Edge-to-Aggr'
        elif node_type == 'Aggr':
            return 'Aggr-to-Edge' if if_index <= self.half_ports else 'Aggr-to-Core'
        elif node_type == 'Core':
            return 'Core-to-Aggr'
        return 'Unknown'

# ===============================================================
# Generic Log Processing (Unchanged)
# ===============================================================
def process_pfc_log(filepath):
    """
    Parses a PFC log file to extract pause intervals for each port.
    (This function is topology-agnostic and remains unchanged.)
    """
    try:
        column_names = ['TimeStep', 'NodeID', 'NodeType', 'IfIndex', 'PfcType']
        df = pd.read_csv(filepath, sep=' ', header=None, names=column_names,
                         dtype={'TimeStep': 'uint64', 'NodeID': 'uint32', 'NodeType': 'uint32', 'IfIndex': 'uint32', 'PfcType': 'uint32'})
    except FileNotFoundError:
        print(f"Error: File not found '{filepath}'")
        return None
    except Exception as e:
        print(f"An error occurred while reading or parsing the file: {e}")
        return None

    if df.empty:
        print("Warning: Log file is empty or improperly formatted.")
        return []

    df.sort_values(by='TimeStep', inplace=True)
    sim_end_time = df['TimeStep'].max()

    intervals = []
    grouped = df.groupby(['NodeID', 'IfIndex'])

    for (node_id, if_index), group_df in grouped:
        last_pause_start = None
        for _, row in group_df.iterrows():
            if row['PfcType'] == 1: # Pause ON
                if last_pause_start is None:
                    last_pause_start = row['TimeStep']
            elif row['PfcType'] == 0: # Pause OFF (Resume)
                if last_pause_start is not None:
                    intervals.append({
                        'NodeID': node_id,
                        'IfIndex': if_index,
                        'StartTime': last_pause_start,
                        'EndTime': row['TimeStep']
                    })
                    last_pause_start = None
                else:
                    # This can happen if logging starts mid-pause
                    pass

        # If a pause was active at the end of the simulation
        if last_pause_start is not None:
            intervals.append({
                'NodeID': node_id,
                'IfIndex': if_index,
                'StartTime': last_pause_start,
                'EndTime': sim_end_time
            })
    return intervals

def calculate_and_print_pause_stats(intervals, time_unit='ns'):
    """
    Calculates total pause time and count for each port and prints stats.
    (This function is topology-agnostic and remains unchanged.)
    """
    if not intervals:
        print("No pause data available for statistics.")
        return
    stats_df = pd.DataFrame(intervals)
    stats_df['Duration'] = stats_df['EndTime'] - stats_df['StartTime']
    port_stats = stats_df.groupby(['NodeID', 'IfIndex']).agg(
        TotalPauseDuration=('Duration', 'sum'),
        PauseCount=('Duration', 'size')
    ).reset_index()
    port_stats.sort_values(by='TotalPauseDuration', ascending=False, inplace=True)
    port_stats.rename(columns={'TotalPauseDuration': f'TotalPauseDuration ({time_unit})'}, inplace=True)
    print("\n--- PFC Pause Statistics Per Port ---")
    print(port_stats.to_string(index=False))
    print("---------------------------------\n")

# ===============================================================
# Fat-Tree Specific Analysis Functions
# ===============================================================
def calculate_fat_tree_detailed_stats(intervals, topo, time_unit='ns'):
    """
    Calculates and prints detailed pause statistics for different port types
    in a Fat-Tree topology.
    """
    if not intervals:
        print("No detailed pause data available for analysis.")
        return

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']
    df['PortType'] = df.apply(topo.get_port_type, axis=1)

    print("\n--- [Overall] Detailed Pause Duration Analysis by Port Type ---")
    
    port_total_pause = df.groupby(['NodeID', 'IfIndex', 'PortType'])['Duration'].sum().reset_index()
    
    port_types_to_analyze = [
        'Edge-to-Aggr', 'Aggr-to-Edge', 'Aggr-to-Core', 'Core-to-Aggr'
    ]
    
    for port_type in port_types_to_analyze:
        ports_df = port_total_pause[port_total_pause['PortType'] == port_type]
        if not ports_df.empty:
            avg_pause = ports_df['Duration'].mean()
            min_pause = ports_df['Duration'].min()
            max_pause = ports_df['Duration'].max()
            print(f"\n{port_type} Ports:")
            print(f"  - Average Pause Duration: {avg_pause:.2f} {time_unit}")
            print(f"  - Minimum Pause Duration: {min_pause} {time_unit}")
            print(f"  - Maximum Pause Duration: {max_pause} {time_unit}")
        else:
            print(f"\nNo pause data found for {port_type} ports.")
            
    print("----------------------------------------------------------\n")

def calculate_fat_tree_imbalance_stats(intervals, topo, time_unit='ns'):
    """
    Analyzes pause imbalance for traffic destined for each Edge switch from its
    connected Aggregation switches.
    """
    if not intervals:
        print("No data available for imbalance analysis.")
        return

    df = pd.DataFrame(intervals)
    df['Duration'] = df['EndTime'] - df['StartTime']
    df['PortType'] = df.apply(topo.get_port_type, axis=1)

    # We are interested in traffic from Aggregation switches TO Edge switches
    aggr_to_edge_ports = df[df['PortType'] == 'Aggr-to-Edge'].copy()
    
    if aggr_to_edge_ports.empty:
        print("\n--- [Imbalance Analysis] No Aggr-to-Edge pause data found. ---\n")
        return

    # Calculate total pause per port first
    port_total_pause = aggr_to_edge_ports.groupby(['NodeID', 'IfIndex'])['Duration'].sum().reset_index()

    # Assumption: The port index (IfIndex) on an Aggr switch determines which
    # Edge switch in the pod it connects to.
    # Eg: Aggr Port 1 -> 1st Edge, Aggr Port 2 -> 2nd Edge, etc.
    def get_target_edge_id(row):
        aggr_id = row['NodeID']
        if_index = row['IfIndex']
        # Find which pod this Aggr switch belongs to
        aggr_local_id = aggr_id - topo.id_offset_aggr
        pod_index = aggr_local_id // topo.num_aggr_per_pod
        # Find the target Edge switch's local index within the pod
        edge_local_index_in_pod = if_index - 1
        # Calculate the global Edge switch ID
        target_edge_id = topo.id_offset_edge + (pod_index * topo.num_edge_per_pod) + edge_local_index_in_pod
        return target_edge_id

    port_total_pause['TargetEdgeID'] = port_total_pause.apply(get_target_edge_id, axis=1)

    print("\n--- [Imbalance Analysis] Pause Distribution on Links to Each Edge Switch ---")
    
    grouped_by_target_edge = port_total_pause.groupby('TargetEdgeID')
    
    for edge_id, group_df in grouped_by_target_edge:
        print(f"\n--- Target Edge Switch {int(edge_id)} ---")
        
        # 1. Print pause duration from each source Aggregation switch port
        print("  Pause Durations from Source Aggr Ports:")
        for _, row in group_df.sort_values('NodeID').iterrows():
            source_aggr_id = row['NodeID']
            duration = row['Duration']
            print(f"    - From Aggr Node {source_aggr_id}: {duration} {time_unit}")

        # 2. Calculate and print summary statistics for this group
        durations = group_df['Duration']
        max_val = durations.max()
        min_val = durations.min()
        
        if len(durations) > 1 and max_val != min_val:
            mean_val = durations.mean()
            range_val = max_val - min_val
            # ddof=0 for population variance, as we have all links to this switch
            variance_val = durations.var(ddof=0)
            std_dev_val = durations.std(ddof=0)
            cv_val = (std_dev_val / mean_val) if mean_val > 0 else 0.0
        else:
            mean_val = durations.mean()
            range_val, variance_val, std_dev_val, cv_val = 0, 0, 0, 0

        print("\n  Statistics Summary:")
        print(f"    - Mean: {mean_val:.2f} {time_unit}")
        print(f"    - Max: {max_val} {time_unit}")
        print(f"    - Min: {min_val} {time_unit}")
        print(f"    - Range: {range_val} {time_unit}")
        print(f"    - Variance: {variance_val:.2f} {time_unit}²")
        print(f"    - Std Dev: {std_dev_val:.2f} {time_unit}")
        print(f"    - Coefficient of Variation (CV): {cv_val:.4f}")
        
    print("----------------------------------------------------------------------\n")

# ===============================================================
# Plotting Functions
# ===============================================================
def generate_fat_tree_plot_group(topo, pod_of_interest=0):
    """
    Generates a set of ports to highlight for plotting, focusing on a specific
    pod and all core switches.
    """
    group_ports = set()

    # 1. Add all ports on all Core switches
    for i in range(topo.num_core):
        core_id = topo.id_offset_core + i
        for port in range(1, topo.ports_per_switch + 1):
            group_ports.add((core_id, port))

    # 2. Add all ports on all Aggr switches in the pod of interest
    pod_start_aggr_id = topo.id_offset_aggr + (pod_of_interest * topo.num_aggr_per_pod)
    for i in range(topo.num_aggr_per_pod):
        aggr_id = pod_start_aggr_id + i
        for port in range(1, topo.ports_per_switch + 1):
            group_ports.add((aggr_id, port))

    # 3. Add all ports on all Edge switches in the pod of interest
    pod_start_edge_id = topo.id_offset_edge + (pod_of_interest * topo.num_edge_per_pod)
    for i in range(topo.num_edge_per_pod):
        edge_id = pod_start_edge_id + i
        for port in range(1, topo.ports_per_switch + 1):
            group_ports.add((edge_id, port))
            
    return group_ports

def plot_pause_timeline(intervals, topo, output_file, time_unit='ns'):
    if not intervals:
        print("No complete pause intervals found, cannot generate plot.")
        return
        
    plot_df = pd.DataFrame(intervals)
    plot_df['PortLabel'] = plot_df.apply(lambda row: f"Node {row['NodeID']}-Port {row['IfIndex']}", axis=1)
    
    pod_to_plot = 0
    print(f"Generating port group for plot: Pod {pod_to_plot} and all Core switches...")
    target_group = generate_fat_tree_plot_group(topo, pod_of_interest=pod_to_plot)
    
    filtered_df = plot_df[plot_df.apply(lambda row: (row['NodeID'], row['IfIndex']) in target_group, axis=1)]
    
    if filtered_df.empty:
        print(f"Warning: No pause events found for Pod {pod_to_plot} or Core switches. Cannot generate plot.")
        return
        
    ordered_labels = sorted(filtered_df['PortLabel'].unique())
    y_pos_map = {label: i for i, label in enumerate(ordered_labels)}
    
    fig_height = max(6, len(ordered_labels) * 0.4)
    fig, ax = plt.subplots(figsize=(15, fig_height))
    
    for _, row in filtered_df.iterrows():
        y = y_pos_map[row['PortLabel']]
        start = row['StartTime']
        duration = row['EndTime'] - row['StartTime']
        ax.barh(y, duration, left=start, height=0.6, color='darkorange', alpha=0.8, label='Paused')
        
    ax.set_yticks(range(len(ordered_labels)))
    ax.set_yticklabels(ordered_labels)
    ax.set_xlabel(f"Time ({time_unit})")
    ax.ticklabel_format(style='sci', axis='x', scilimits=(0,0), useMathText=True)
    ax.set_title(f"PFC Pause Timeline for Fat-Tree (Pod {pod_to_plot} & Cores)", fontsize=14)
    ax.set_ylabel("Node and Port Interface")
    ax.grid(True, axis='x', linestyle='--', alpha=0.6)
    
    # Create a single legend entry
    handles, labels = plt.gca().get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label: 
        ax.legend(by_label.values(), by_label.keys())
        
    plt.tight_layout()
    try:
        plt.savefig(output_file, bbox_inches='tight', dpi=300)
        print(f"Plot successfully saved to: {output_file}")
    except Exception as e:
        print(f"Error saving plot: {e}")
    plt.close()

def main():
    """
    Main function to handle command-line arguments and call processing and plotting functions.
    """
    parser = argparse.ArgumentParser(description="Analyze and visualize PFC (Priority Flow Control) pause/resume logs for a Fat-Tree topology.")
    parser.add_argument("input", help="Input PFC log file path.")
    parser.add_argument("-o", "--output", default="pfc_timeline_fattree.pdf",
                        help="Output plot file path (e.g., pfc.pdf, pfc.png). Default: pfc_timeline_fattree.pdf")
    parser.add_argument("-u", "--unit", default="ns",
                        help="Time unit for display (e.g., ns, us). Default: ns")
    parser.add_argument("-k", "--k_val", type=int, default=8,
                        help="The 'k' value of the k-ary Fat-Tree topology. Default: 8")
    parser.add_argument("--plot", action="store_true",
                        help="Enable this flag to generate and save the PFC timeline plot.")
    args = parser.parse_args()

    if args.plot:
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")

    # Initialize the topology
    try:
        fat_tree_topo = FatTreeTopology(k=args.k_val)
        print(f"Analyzing for a k={args.k_val} Fat-Tree topology.")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print("Starting log file processing...")
    pfc_intervals = process_pfc_log(args.input)

    if pfc_intervals:
        print(f"Processing complete. Found {len(pfc_intervals)} pause intervals.")
        
        # 1. Generic per-port statistics
        calculate_and_print_pause_stats(pfc_intervals, args.unit)
        
        # 2. Fat-Tree specific overall statistics by port type
        calculate_fat_tree_detailed_stats(pfc_intervals, fat_tree_topo, args.unit)

        # 3. Fat-Tree specific imbalance analysis
        calculate_fat_tree_imbalance_stats(pfc_intervals, fat_tree_topo, args.unit)

        if args.plot:
            print("Generating plot...")
            plot_pause_timeline(pfc_intervals, fat_tree_topo, args.output, args.unit)

if __name__ == "__main__":
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans'] 
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.autolayout'] = True
    main()