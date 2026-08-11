#!/usr/bin/python3
from genericpath import exists
import fcntl
import shlex
import subprocess
import os
import time
from xmlrpc.client import boolean
import numpy as np
import copy
import shutil
import random
from datetime import datetime
import sys
import os
import argparse
from datetime import date

from artifact.common.run_manifest import append_runtime_manifest

# randomID
random.seed(int(datetime.now().timestamp()))
MAX_RAND_RANGE = 1000000000


def append_history(path, content):
    """Append one complete history record without interleaving writers."""
    with open(path, "a") as history:
        fcntl.flock(history, fcntl.LOCK_EX)
        history.write(content)
        history.flush()
        fcntl.flock(history, fcntl.LOCK_UN)


def simulator_command(config_name, output_log):
    """Return the simulator command and whether it can run without Waf."""
    if os.environ.get("ARTIFACT_DIRECT_RUN") == "1":
        simulator = os.path.join(
            os.getcwd(), "build", "scratch", "network-load-balance",
            "network-load-balance",
        )
        command = [simulator, config_name]
        rendered = "{} > {} 2>&1".format(
            " ".join(shlex.quote(argument) for argument in command),
            shlex.quote(output_log),
        )
        return command, rendered

    rendered = "./waf --run 'network-load-balance {}' > {} 2>&1".format(
        config_name, output_log
    )
    return None, rendered


def run_simulator(command, rendered, output_log):
    if command is None:
        return os.system(rendered)

    with open(output_log, "w") as output:
        completed = subprocess.run(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return completed.returncode

# config template
# MODIFICATION START: Replaced the static ENABLE_QCN line with a placeholder
config_template = """TOPOLOGY_FILE config/{topo}.txt
FLOW_FILE config/{flow}.txt
WEIGHT_FILE config/{topo}_weight.txt
GROUP_FILE config/{topo}_group.txt

FLOW_INPUT_FILE mix/output/{id}/{id}_in.txt
CNP_OUTPUT_FILE mix/output/{id}/{id}_out_cnp.txt
FCT_OUTPUT_FILE mix/output/{id}/{id}_out_fct.txt
JCT_OUTPUT_FILE mix/output/{id}/{id}_out_jct.txt
PFC_OUTPUT_FILE mix/output/{id}/{id}_out_pfc.txt
QLEN_MON_FILE mix/output/{id}/{id}_out_qlen.txt
VOQ_MON_FILE mix/output/{id}/{id}_out_voq.txt
VOQ_MON_DETAIL_FILE mix/output/{id}/{id}_out_voq_per_dst.txt
UPLINK_MON_FILE mix/output/{id}/{id}_out_uplink.txt
DOWNLINK_MON_FILE mix/output/{id}/{id}_out_downlink.txt
SPINE_DL_MON_FILE mix/output/{id}/{id}_out_spine_dl.txt
THROUGHPUT_MON_FILE mix/output/{id}/{id}_out_throughput.txt
CONN_MON_FILE mix/output/{id}/{id}_out_conn.txt
EST_ERROR_MON_FILE mix/output/{id}/{id}_out_est_error.txt
FLOW_DROP_FILE mix/output/{id}/{id}_out_flow_drop.txt
DROP_INCAST_FILE mix/output/{id}/{id}_out_drop_incast.txt
PFC_INCAST_FILE mix/output/{id}/{id}_out_pfc_incast.txt
RETRANSMIT_FILE mix/output/{id}/{id}_out_retransmit.txt
RATE_OUTPUT_FILE mix/output/{id}/{id}_out_rate.txt

WORKLOAD_TYPE {workload_type}
AI_MESSAGE_SIZE {ai_message_size}
AI_MESSAGE_SIZES_FILE {ai_message_sizes_file}
AI_NODES_PER_GROUP {ai_nodes_per_group}
NUM_ROUNDS {num_rounds}

QLEN_MON_START {qlen_mon_start}
QLEN_MON_END {qlen_mon_end}
SW_MONITORING_INTERVAL {sw_monitoring_interval}

FLOWGEN_START_TIME {flowgen_start_time}
FLOWGEN_STOP_TIME {flowgen_stop_time}
BUFFER_SIZE {buffer_size}

CC_MODE {cc_mode}
LANES_PER_DESTINATION {lanes_per_destination}
LB_MODE {lb_mode}
AR_MODE {ar_mode}
ENABLE_PFC {enabled_pfc}
ENABLE_IRN {enabled_irn}
ENABLE_DCP {enabled_dcp}
ENABLE_DCP_ACK_OPT {enabled_dcp_ack_opt}
ENABLE_IDEAL {enabled_ideal}

CONWEAVE_TX_EXPIRY_TIME {cwh_tx_expiry_time}
CONWEAVE_REPLY_TIMEOUT_EXTRA {cwh_extra_reply_deadline}
CONWEAVE_PATH_PAUSE_TIME {cwh_path_pause_time}
CONWEAVE_EXTRA_VOQ_FLUSH_TIME {cwh_extra_voq_flush_time}
CONWEAVE_DEFAULT_VOQ_WAITING_TIME {cwh_default_voq_waiting_time}

ALPHA_RESUME_INTERVAL 1
RATE_DECREASE_INTERVAL {rate_decrease_interval}
CLAMP_TARGET_RATE 0
RP_TIMER {rp_timer}
FAST_RECOVERY_TIMES 1
TIMEOUT_SLOWSTART_MODE {timeout_slowstart_mode}
EWMA_GAIN {ewma_gain}
RATE_AI {ai}Mb/s
RATE_HAI {hai}Mb/s
MIN_RATE 100Mb/s
DCTCP_RATE_AI {dctcp_ai}Mb/s

ERROR_RATE_PER_LINK {error_rate:.8f}
L2_CHUNK_SIZE 4000
L2_ACK_INTERVAL 1
L2_BACK_TO_ZERO 0

RATE_BOUND 1
HAS_WIN {has_win}
VAR_WIN {var_win}
WINDOW_SIZE {window_size}
FAST_REACT {fast_react}
MI_THRESH {mi}
INT_MULTI {int_multi}
GLOBAL_T 1
U_TARGET 0.95
MULTI_RATE 0
SAMPLE_FEEDBACK 0

ENABLE_QCN {enable_qcn}
USE_DYNAMIC_PFC_THRESHOLD 1
PACKET_PAYLOAD_SIZE 1000


LINK_DOWN 0 0 0
KMAX_MAP {kmax_map}
KMIN_MAP {kmin_map}
PMAX_MAP {pmax_map}
LOAD {load}
RANDOM_SEED 1

IRN_RTOH_HIGH {irn_rto_high}
IRN_RTO_LOW {irn_rto_low}
"""
# MODIFICATION END


# LB/CC mode matching
cc_modes = {
    "dcqcn": 1,
    "dcqcn_dst": 2,
    "hpcc": 3,
    "none": 4,
    "dcqcn_lane": 5,  # Per-Lane DCQCN
    "timely": 7,
    "dctcp": 8,
}

lb_modes = {
    "fecmp": 0,
    "rps": 1,
    "drill": 2,
    "conga": 3,
    "adaptive": 4,  # Adaptive Routing Packet Spraying
    "weightadaptive": 5,  # Weighted Spraying
    "letflow": 6,
    "drillgroup": 7,  # DRILL-style: WCMP across groups + spray within group
    "conweave": 9,
    "sglb": 10,       # SGLB (Spine-guided LB for leaf-spine)
}

ar_modes = {
    "noar": 0,
    "ar": 1,
    "arsp": 2,  # adaptive routing with selective repeat(ToDo)
}

topo2bdp = {
    "leaf_spine_128_100G_OS2": 104000,  # 2-tier -> all 100Gbps
    "leaf_spine_L8_S16_100G_OS1": 104000,  # 2-tier -> all 100Gbps
    "leaf_spine_L2_S4_100G_OS1": 104000,  # 2-tier -> all 100Gbps
    "leaf_spine_L2_S4_100G_OS2": 104000,  # 2-tier -> all 100Gbps
    "leaf_spine_L2_S8_100G_OS1": 104000,  # 2-tier -> all 100Gbps
    "leaf_spine_L16_S16_100G_OS1": 104000,  # 2-tier -> all 100Gbps
    # Add 200G Topologies
    "leaf_spine_L8_S16_200G_OS1": 204000,  # 2-tier -> all 200Gbps
    "fat_k8_200G_OS1": 306000,  # 3-tier -> all 200Gbps
    # Add 400G Topologies
    "leaf_spine_L8_S8_400G_OS2": 404000,
    "leaf_spine_L8_S16_400G_OS1": 404000,
    "leaf_spine_L2_S4_400G_OS1": 404000,
    "fat_k8_400G_OS1": 606000,  # 3-tier -> all 400Gbps
    # Added Asymmetric Topologies
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym10pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.5_OS2": 104000,
    "leafspine_L8_S8_100G_Asym20pct_Ratio0.2_OS2": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym10pct_Ratio0.2_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.5_OS1": 104000,
    "leafspine_L8_S16_100G_Asym20pct_Ratio0.2_OS1": 104000,
    # New naming convention produced by config/test/leaf_spine_topo_asy_gen.py
    # Three asymmetry modes (bandwidth / link-fail / link-delay)
    # NOTE: for delay-asymmetry topos, BDP stays at 104000 (not recomputed
    # from the inflated RTT); main.cc relaxes the maxBdp assertion accordingly.
    "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1": 104000,
    "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1": 104000,
    "leafspine_L8_S16_100G_AsymFail1pct_OS1": 104000,
    "leafspine_L8_S16_100G_AsymFail10pct_OS1": 104000,
    "leafspine_L8_S16_100G_AsymDelay10pct_5us_OS1": 104000,
    "leafspine_L8_S16_100G_AsymDelay10pct_10us_OS1": 104000,
    # three tier topologies
    "fat_k8_100G_OS2": 156000,  # 3-tier -> all 100Gbps
    "fat_k8_100G_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l28_s8_faill1_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l28_s8_faill2_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l28_s8_nofail_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l28_s8_faill12_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l24_s8_faill23_OS1": 156000,  # 3-tier -> all 100Gbps
    "three_layer_p4_tor4_l19_l28_s8_failhalf_OS1": 156000,  # 3-tier -> all 100Gbps
    "bigswitch_H8_100G_OS1": 104000,  # BigSwitch -> all 100Gbps
    "bigswitch_H16_100G_OS1": 104000,  # BigSwitch -> all 100Gbps
    "bigswitch_H61_100G_OS1": 104000,  # BigSwitch -> all 100Gbps
    "bigswitch_H128_100G_OS1": 104000,  # BigSwitch -> all 100Gbps
}

FLOWGEN_DEFAULT_TIME = 2.0  # see /traffic_gen/traffic_gen.py::base_t

def generate_zipfian_distribution(n, alpha):
    """Generate Zipfian distribution weights for n items with skewness alpha"""
    import numpy as np

    weights = np.array([1.0 / (i ** alpha) for i in range(1, n + 1)])
    # Normalize to sum to 1
    weights = weights / np.sum(weights)
    return weights

def generate_alltoallv_message_sizes(pattern, base_size, group_size):
    """Generate message size matrix for AlltoallV workload

    Args:
        pattern: Traffic pattern type
        base_size: Base message size (total amount per GPU for new modes)
        group_size: Number of GPUs in the group

    Returns:
        List of message sizes in row-major order (src0->dst0, src0->dst1, ..., src1->dst0, ...)
    """
    import numpy as np
    import random

    # Set seed for reproducibility
    np.random.seed(42)
    random.seed(42)

    total_pairs = group_size * group_size

    if pattern == "uniform" or pattern == "random_uniform":
        # Mode 1: Random (Uniform)
        # Each GPU sends the same total amount, uniformly distributed
        msg_size_per_flow = base_size // (group_size - 1)  # Exclude self-communication
        sizes = []

        for src in range(group_size):
            for dst in range(group_size):
                if src == dst:
                    sizes.append(0)  # No self-communication
                else:
                    sizes.append(msg_size_per_flow)
        return sizes

    elif pattern == "zipfian":
        # Mode 2: Zipfian (Flow-level skew)
        # Each GPU sends the same total, but Zipfian-distributed across flows
        alpha = 0.8  # Skewness factor
        sizes = []

        # Generate Zipfian weights for flows to other GPUs
        zipf_weights = generate_zipfian_distribution(group_size - 1, alpha)

        for src in range(group_size):
            flow_sizes = []
            weight_idx = 0
            for dst in range(group_size):
                if src == dst:
                    flow_sizes.append(0)  # No self-communication
                else:
                    # Distribute total amount according to Zipfian weights
                    flow_size = int(base_size * zipf_weights[weight_idx])
                    flow_sizes.append(flow_size)
                    weight_idx += 1

            # Normalize to ensure exact total amount
            total_sent = sum(flow_sizes)
            if total_sent > 0:
                scale_factor = base_size / total_sent
                flow_sizes = [int(size * scale_factor) if size > 0 else 0 for size in flow_sizes]

            sizes.extend(flow_sizes)
        return sizes

    elif pattern == "zipfian_incast":
        # Mode 2b: Zipfian incast (receiver-level skew)
        # base_size means the total received bytes of the hottest receiver
        alpha = 0.8
        sizes = []

        receiver_weights = generate_zipfian_distribution(group_size, alpha)
        max_weight = max(receiver_weights)

        # Receiver totals scaled so the hottest receiver gets exactly base_size
        receiver_totals = [base_size * (w / max_weight) for w in receiver_weights]

        traffic_matrix = np.zeros((group_size, group_size), dtype=int)

        # Evenly split each receiver's load across all other senders
        for dst in range(group_size):
            per_sender = receiver_totals[dst] / (group_size - 1)
            for src in range(group_size):
                if src != dst:
                    traffic_matrix[src, dst] = int(per_sender)

        # Fix rounding error per receiver column
        for dst in range(group_size):
            target = int(receiver_totals[dst])
            current = int(np.sum(traffic_matrix[:, dst]))
            diff = target - current
            if diff != 0:
                for src in range(group_size):
                    if src != dst:
                        traffic_matrix[src, dst] += diff
                        break

        for src in range(group_size):
            for dst in range(group_size):
                sizes.append(int(traffic_matrix[src, dst]))

        return sizes

    elif pattern == "moe" or pattern == "realistic_moe":
        # Mode 3: Realistic MoE (Receiver skew for incast)
        # Same total sent per GPU, but different total received (Zipfian distribution)
        receiver_alpha = 0.8  # Receiver skewness

        # Uniform sender capacities (same total per GPU)
        sender_capacity = base_size

        # Generate receiver capacities using Zipfian distribution
        receiver_weights = generate_zipfian_distribution(group_size, receiver_alpha)

        # Scale receiver capacities to meaningful amounts
        total_system_traffic = base_size * group_size * (group_size - 1)
        receiver_capacities = receiver_weights * total_system_traffic

        # Create traffic matrix
        traffic_matrix = np.zeros((group_size, group_size))

        # Initialize with uniform distribution from each sender
        for src in range(group_size):
            for dst in range(group_size):
                if src != dst:
                    traffic_matrix[src, dst] = sender_capacity / (group_size - 1)

        # Iterative scaling algorithm to satisfy receiver constraints while keeping sender uniform
        max_iterations = 100
        tolerance = 0.01

        for iteration in range(max_iterations):
            # Adjust for receiver constraints
            for dst in range(group_size):
                current_received = np.sum(traffic_matrix[:, dst])
                if current_received > 0:
                    scale_factor = receiver_capacities[dst] / current_received
                    traffic_matrix[:, dst] *= scale_factor
                    traffic_matrix[dst, dst] = 0  # No self-communication

            # Re-normalize sender constraints (keep uniform sending)
            for src in range(group_size):
                current_sent = np.sum(traffic_matrix[src, :])
                if current_sent > 0:
                    scale_factor = sender_capacity / current_sent
                    traffic_matrix[src, :] *= scale_factor
                    traffic_matrix[src, src] = 0  # No self-communication

            # Check convergence for receiver constraints only
            receiver_errors = [abs(np.sum(traffic_matrix[:, dst]) - receiver_capacities[dst]) / receiver_capacities[dst]
                             for dst in range(group_size)]

            if max(receiver_errors) < tolerance:
                break

        # Convert to integer sizes and flatten
        sizes = []
        for src in range(group_size):
            for dst in range(group_size):
                sizes.append(int(traffic_matrix[src, dst]))

        return sizes

    # Legacy patterns for backward compatibility
    elif pattern == "power2":
        # Message sizes follow powers of 2: base_size * 2^(i%4)
        sizes = []
        for i in range(total_pairs):
            power = i % 4
            sizes.append(base_size * (2 ** power))
        return sizes
    elif pattern == "linear":
        # Linear increase: base_size * (1 + i/total_pairs)
        sizes = []
        for i in range(total_pairs):
            multiplier = 1 + (i / total_pairs)
            sizes.append(int(base_size * multiplier))
        return sizes
    elif pattern == "random":
        # Random sizes between base_size/4 and base_size*4
        sizes = []
        for i in range(total_pairs):
            factor = random.uniform(0.25, 4.0)
            sizes.append(int(base_size * factor))
        return sizes
    else:
        print(f"WARNING: Unknown pattern '{pattern}', using uniform")
        return [base_size // (group_size - 1) if i % group_size != i // group_size else 0
                for i in range(total_pairs)]

def save_alltoallv_message_sizes(config_id, groups, message_sizes_per_group):
    """Save AlltoallV message sizes to a configuration file"""
    filename = f"mix/output/{config_id}/{config_id}_alltoallv_msg_sizes.txt"
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, 'w') as f:
        f.write(f"# AlltoallV Message Sizes Configuration\n")
        f.write(f"# Groups: {len(groups)}\n")
        for g, group in enumerate(groups):
            group_size = len(group)
            f.write(f"# Group {g}: {group_size} nodes\n")
            sizes = message_sizes_per_group[g]
            for i, size in enumerate(sizes):
                src_idx = i // group_size
                dst_idx = i % group_size
                f.write(f"{g} {src_idx} {dst_idx} {size}\n")

    return filename

def main():
    # make directory if not exists
    isExist = os.path.exists(os.getcwd() + "/mix/output/")
    if not isExist:
        os.makedirs(os.getcwd() + "/mix/output/")
        print("The new directory is created - {}".format(os.getcwd() + "/mix/output/"))

    parser = argparse.ArgumentParser(description='run simulation')
    parser.add_argument('--cc', dest='cc', action='store',
                        default='dcqcn', help="hpcc/dcqcn/dcqcn_lane/timely/dctcp/none (default: dcqcn)")
    parser.add_argument('--lanes', dest='lanes', action='store',
                        type=int, default=4, help="Number of lanes per src-dst pair for dcqcn_lane mode (default: 4)")
    parser.add_argument('--lb', dest='lb', action='store',
                        default='fecmp', help="fecmp/pecmp/drill/conga (default: fecmp)")
    parser.add_argument('--pfc', dest='pfc', action='store',
                        type=int, default=1, help="enable PFC (default: 1)")
    parser.add_argument('--irn', dest='irn', action='store',
                        type=int, default=0, choices=[0, 1, 2, 3, 4],
                        help="Loss recovery mode: 0=None, 1=IRN, 2=DCP, 3=Ideal, 4=DCPAckOpt (default: 0)")
    #modification begin
    parser.add_argument('--armode', dest='armode', action='store',
                        default='noar', help="noar/ar/arsp(default: noar)")
    #modification end
    parser.add_argument('--simul_time', dest='simul_time', action='store',
                        default='0.1', help="traffic time to simulate (up to 3 seconds) (default: 0.1)")
    parser.add_argument('--buffer', dest="buffer", action='store',
                        default='9', help="switch buffer size in MB/port: 0=legacy fallback (9MB), -1=Tomahawk dynamic auto-detect, >0=explicit MB/port (supports decimals, e.g. 0.25) (default: 9)")
    parser.add_argument('--netload', dest='netload', action='store', type=int,
                        default=40, help="Network load at NIC to generate traffic (default: 40.0)")
    parser.add_argument('--netload_pattern', dest='netload_pattern', action='store',
                        default='uniform', help="Message size pattern for AlltoallV: uniform/zipfian/moe/power2/linear/random (default: uniform)")
    parser.add_argument('--bw', dest="bw", action='store',
                        default='100', help="the NIC bandwidth (Gbps) (default: 100)")
    parser.add_argument('--topo', dest='topo', action='store',
                        default='leaf_spine_128_100G_OS2', help="the name of the topology file (default: leaf_spine_128_100G_OS2)")
    parser.add_argument('--cdf', dest='cdf', action='store',
                        default='AliStorage2019', help="the name of the cdf file (default: AliStorage2019)")
    parser.add_argument('--enforce_win', dest='enforce_win', action='store',
                        type=int, default=0, help="enforce to use window scheme (default: 0)")
    parser.add_argument('--windowSize', dest='windowSize', action='store',
                        type=int, default=0, help="the window size (0 means no window) (default: 0)")
    parser.add_argument('--timeout_slowstart_mode', dest='timeout_slowstart_mode', action='store',
                        type=int, default=0,
                        help="Timeout slow start mode (default: 0)")
    parser.add_argument('--sw_monitoring_interval', dest='sw_monitoring_interval', action='store',
                        type=int, default=10000, help="interval of sampling statistics for queue status (default: 10000ns)")
    parser.add_argument('--error_rate', dest='error_rate', action='store',
                        type=float, default=0.0, help="Error rate per link (default: 0.0)")
    parser.add_argument('--flowgen_mode', dest='flowgen_mode', action='store',
                        default='src', choices=['src', 'dst', 'inter_leaf'],
                        help="Traffic generation mode: src or dst (default: src)")
    # ✅ 新增 RTO 設定參數
    parser.add_argument('--rto_high', dest='rto_high', action='store',
                        type=int, default=300, help="High RTO threshold (default: 300)")
    parser.add_argument('--rto_low', dest='rto_low', action='store',
                        type=int, default=100, help="Low RTO threshold (default: 100)")
    # ECN marking probability parameter
    parser.add_argument('--ecn_pmax', dest='ecn_pmax', action='store',
                        type=float, default=0.2, help="ECN marking probability (default: 0.2)")
    # RP_TIMER parameter for rate control
    parser.add_argument('--rp_timer', dest='rp_timer', action='store',
                        type=int, default=300, help="Rate increase timer in microseconds (default: 300)")
    parser.add_argument('--rate_decrease_interval', dest='rate_decrease_interval', action='store',
                        type=int, default=4, help="DCQCN rate decrease interval (default: 4)")

    # AI workload grouping parameter
    parser.add_argument('--ai_nodes_per_group', dest='ai_nodes_per_group', action='store',
                        type=int, default=8, help="Number of nodes per AI workload group (default: 8)")


    # #### CONWEAVE PARAMETERS ####
    # parser.add_argument('--cwh_extra_reply_deadline', dest='cwh_extra_reply_deadline', action='store',
    #                     type=int, default=4, help="extra-timeout, where reply_deadline = base-RTT + extra-timeout (default: 4us)")
    # parser.add_argument('--cwh_path_pause_time', dest='cwh_path_pause_time', action='store',
    #                     type=int, default=16, help="Time to pause the path with ECN feedback (default: 8us")
    # parser.add_argument('--cwh_extra_voq_flush_time', dest='cwh_extra_voq_flush_time', action='store',
    #                     type=int, default=16, help="Extra VOQ Flush Time (default: 8us for IRN)")
    # parser.add_argument('--cwh_default_voq_waiting_time', dest='cwh_default_voq_waiting_time', action='store',
    #                     type=int, default=400, help="Default VOQ Waiting Time (default: 400us)")
    # parser.add_argument('--cwh_tx_expiry_time', dest='cwh_tx_expiry_time', action='store',
    #                     type=int, default=1000, help="timeout value of ConWeave Tx for CLEAR signal (default: 1000us)")

    args = parser.parse_args()

    # make running ID of this config
    # need to check directory exists or not
    isExist = True
    config_ID = 0
    while (isExist):
        config_ID = str(random.randrange(MAX_RAND_RANGE))
        isExist = os.path.exists(os.getcwd() + "/mix/output/" + config_ID)

    # input parameters
    cc_mode = cc_modes[args.cc]
    lanes_per_destination = int(args.lanes)
    lb_mode = lb_modes[args.lb]
    ar_mode = ar_modes[args.armode]  # modification
    enabled_pfc = int(args.pfc)
    # enabled_irn = int(args.irn)
    loss_recovery_mode = int(args.irn) # Use a more descriptive name
    # Set flags for the config file based on the loss recovery mode
    enabled_irn_flag = 1 if loss_recovery_mode == 1 else 0
    enabled_dcp_flag = 1 if loss_recovery_mode in (2, 4) else 0
    enabled_ideal_flag = 1 if loss_recovery_mode == 3 else 0
    enabled_dcp_ack_opt_flag = 1 if loss_recovery_mode == 4 else 0
    # ... (code continues)

    bw = int(args.bw)
    buffer = args.buffer
    topo = args.topo
    enforce_win = args.enforce_win
    cdf = args.cdf
    flowgen_start_time = FLOWGEN_DEFAULT_TIME  # default: 2.0
    flowgen_stop_time = flowgen_start_time + \
        float(args.simul_time)  # default: 2.0
    sw_monitoring_interval = int(args.sw_monitoring_interval)

    # Logic for new workload parameters
    workload_type = 0
    ai_message_size = 0
    num_rounds = 1  # Fixed to 1 as requested

    if args.cdf == "Alltoall":
        workload_type = 1
    elif args.cdf == "RingAllreduce":
        workload_type = 2
    elif args.cdf == "TreeAllreduce":
        workload_type = 3
    elif args.cdf == "TreeAllreduceChunked":
        workload_type = 4
    elif args.cdf == "AlltoallV":
        workload_type = 5

    if workload_type != 0:
        ai_message_size = args.netload
    
    # get over-subscription ratio from topoogy name
    netload = args.netload
    oversub = int(topo.replace("\n", "").split("OS")[-1].replace(".txt", ""))
    assert (int(args.netload) % oversub == 0)
    hostload = int(args.netload) / oversub
    assert (hostload > 0)

    # # MODIFICATION START: Set IRN RTO parameters based on topology
    # irn_rto_high = 320  # Default value
    # irn_rto_low = 100   # Default value
    # if "leaf" in topo:
    #     rto_temp = 500
    #     irn_rto_high = rto_temp
    #     irn_rto_low = rto_temp
    # elif "fat" in topo:
    #     irn_rto_high = 320
    #     irn_rto_low = 100
    # # MODIFICATION END

    # 先使用命令行參數的值作為初始值
    irn_rto_high = args.rto_high
    irn_rto_low = args.rto_low

    # Sanity checks
    if (args.cc == "timely" or args.cc == "hpcc") and args.lb == "conweave":
        raise Exception(
            "CONFIG ERROR : ConWeave currently does not support RTT-based protocols. Plz modify its logic accordingly.")
    # # Check if any loss recovery is enabled with PFC
    # if loss_recovery_mode != 0 and enabled_pfc == 1:
    #     raise Exception(
    #         "CONFIG ERROR : If a loss recovery mechanism (IRN or DCP) is active, PFC should be disabled for better performance.")
    # if loss_recovery_mode == 0 and enabled_pfc == 0:
    #     raise Exception(
    #         "CONFIG ERROR : At least one mechanism (PFC, IRN, or DCP) must be enabled.")
    if float(args.simul_time) < 0.000000005:
        raise Exception("CONFIG ERROR : Runtime must be larger than 5ms (= warmup interval).")

    # sniff number of servers
    with open("config/{topo}.txt".format(topo=args.topo), 'r') as f_topo:
        line = f_topo.readline().split(" ")
        n_host = int(line[0]) - int(line[1])

    # assert (hostload >= 0 and hostload < 100)
    
    # MODIFICATION START: Corrected logic for handling flow file based on workload
    if args.cdf in ["Alltoall", "RingAllreduce", "TreeAllreduce", "TreeAllreduceChunked", "AlltoallV"]:
        # For AI workloads, use "none" and skip file generation/checking
        flow = "none"
        print(f"INFO: Using '{flow}.txt' as flow file for '{args.cdf}' workload, skipping generation.")
    else:
        # For other workloads, generate the filename and the file itself if needed
        if args.flowgen_mode == 'dst':
            flow_suffix = "_dst"
        elif args.flowgen_mode == 'inter_leaf':
            flow_suffix = "_inter_leaf"
        else:
            flow_suffix = "" # 默认为 src 模式
        flow = "L_{load:.2f}_CDF_{cdf}_N_{n_host}_T_{time}ms_B_{bw}_flow{suffix}".format(
            load=hostload, cdf=args.cdf, n_host=n_host, time=int(float(args.simul_time)*1000), bw=bw, suffix=flow_suffix)

        # check if the file exists and generate it if not (with file locking for concurrent safety)
        traffic_file_path = os.getcwd() + "/config/" + flow + ".txt"
        lock_file_path = traffic_file_path + ".lock"

        if (exists(traffic_file_path)):
            print("Input traffic file with load:{load:.2f}, cdf:{cdf}, n_host:{n_host} already exists".format(
                load=hostload, cdf=cdf, n_host=n_host))
        else:  # make the input traffic file with file locking
            # Try to acquire lock for traffic generation
            try:
                lock_fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    # We got the lock, check again if file exists (double-check locking pattern)
                    if exists(traffic_file_path):
                        print("Input traffic file with load:{load:.2f}, cdf:{cdf}, n_host:{n_host} was generated by another process".format(
                            load=hostload, cdf=cdf, n_host=n_host))
                    else:
                        print("Generate a input traffic file...")
                        print("python ./traffic_gen/traffic_gen.py -c {cdf} -n {n_host} -l {load} -b {bw} -t {time} -m {mode} -o {output}".format(
                            cdf="./traffic_gen/" + args.cdf + ".txt",
                            n_host=n_host,
                            load=hostload / 100.0,
                            bw=args.bw + "G",
                            time=args.simul_time,
                            mode=args.flowgen_mode,
                            output=traffic_file_path))

                        os.system("python ./traffic_gen/traffic_gen.py -c {cdf} -n {n_host} -l {load} -b {bw} -t {time} -m {mode} -o {output}".format(
                            cdf="./traffic_gen/" + args.cdf + ".txt",
                            n_host=n_host,
                            load=hostload / 100.0,
                            bw=args.bw + "G",
                            time=args.simul_time,
                            mode=args.flowgen_mode,
                            output=traffic_file_path))
                finally:
                    os.close(lock_fd)
                    os.unlink(lock_file_path)  # Remove lock file
            except OSError:
                # Another process is generating the traffic, wait for it to complete
                print("Another process is generating traffic file, waiting...")
                while not exists(traffic_file_path):
                    if not exists(lock_file_path):
                        # Lock file disappeared but traffic file still doesn't exist, might be an error
                        break
                    time.sleep(0.5)  # Wait 500ms before checking again
                print("Traffic file generation completed by another process")
    # MODIFICATION END


    # sanity check - bandwidth
    with open("config/{topo}.txt".format(topo=args.topo), 'r') as f_topo:
        first_line = f_topo.readline().split(" ")
        n_host = int(first_line[0]) - int(first_line[1])
        n_link = int(first_line[2])
        i = 0
        for line in f_topo.readlines()[1:]:
            i += 1
            if (i > n_link):
                break
            parsed = line.split(" ")
            if len(parsed) > 2 and (int(parsed[0]) < n_host or int(parsed[1]) < n_host):
                assert (int(parsed[2].replace("Gbps", "")) == int(bw))
    print("All NIC bandwidth is {bw}Gbps".format(bw=bw))

    ##################################################################
    ##########              ConWeave parameters             ##########
    ##################################################################
    if (lb_mode == 9):
        cwh_extra_reply_deadline = 4  # 4us, NOTE: this is "extra" term to base RTT
        cwh_path_pause_time = 16  # 8us (K_min) or 16us

        if "leaf_spine" in topo or "leafspine" in topo:  # 2-tier
            cwh_extra_voq_flush_time = 16
            cwh_default_voq_waiting_time = 200
            cwh_tx_expiry_time = 300  # 300us
        elif "fat" in topo and enabled_pfc == 0 and loss_recovery_mode != 0:  # 3-tier, Loss Recovery (IRN or DCP)
            cwh_extra_voq_flush_time = 16
            cwh_default_voq_waiting_time = 300
            cwh_tx_expiry_time = 1000  # 1ms
        elif "fat" in topo and enabled_pfc == 1 and loss_recovery_mode == 0:  # 3-tier, Lossless (PFC only)
            cwh_extra_voq_flush_time = 64
            cwh_default_voq_waiting_time = 600
            cwh_tx_expiry_time = 1000  # 1ms
        elif "bigswitch" in topo:  # BigSwitch
            cwh_extra_voq_flush_time = 16
            cwh_default_voq_waiting_time = 200
            cwh_tx_expiry_time = 300
        elif "three" in topo and loss_recovery_mode != 0:  # 3-tier test topology
            cwh_extra_voq_flush_time = 16
            cwh_default_voq_waiting_time = 300
            cwh_tx_expiry_time = 1000  # 1ms
        elif "three" in topo and enabled_pfc == 1 and loss_recovery_mode == 0:  # 3-tier test topology
            cwh_extra_voq_flush_time = 64
            cwh_default_voq_waiting_time = 600
            cwh_tx_expiry_time = 1000  # 1ms
        else:
            raise Exception(
                "Unsupported ConWeave Parameter Setup")
    else:
        #### CONWEAVE PARAMETERS (DUMMY) ####
        cwh_extra_reply_deadline = 4
        cwh_path_pause_time = 16
        cwh_extra_voq_flush_time = 64
        cwh_default_voq_waiting_time = 400
        cwh_tx_expiry_time = 1000

    ##################################################################

    # make directory if not exists
    isExist = os.path.exists(os.getcwd() + "/mix/output/" + config_ID + "/")
    assert (not isExist)
    # if not isExist:
    os.makedirs(os.getcwd() + "/mix/output/" + config_ID + "/")
    print("The new directory is created  - {}".format(os.getcwd() +
          "/mix/output/" + config_ID + "/"))

    config_name = os.getcwd() + "/mix/output/" + config_ID + "/config.txt"
    print("Config filename:{}".format(config_name))

    # # By default, DCQCN uses no window (rate-based).
    # has_win = 0
    # var_win = 0
    # if (cc_mode == 3 or cc_mode == 8 or enforce_win == 1):  # HPCC or DCTCP or enforcement
    #     has_win = 1
    #     var_win = 1
    #     if enforce_win == 1:
    #         print("### INFO: Enforced to use window scheme! ###")

    # Window logic
    if args.windowSize > 0:
        has_win = 1
        var_win = 0
        window_size = args.windowSize
    else:
        has_win = 0
        var_win = 0
        window_size = 0

    # record to history
    simulday = datetime.now().strftime("%m/%d/%y")
    # MODIFICATION START: Added irn_rto_high and irn_rto_low to the history log
    with open("./mix/.history", "a") as history:
        fcntl.flock(history, fcntl.LOCK_EX)
        history_row = "{simulday},{config_ID},{cc_mode},{lb_mode},{ar_mode},{cwh_tx_expiry_time},{cwh_extra_reply_deadline},{cwh_path_pause_time},{cwh_extra_voq_flush_time},{cwh_default_voq_waiting_time},{pfc},{irn},{has_win},{var_win},{window_size},{topo},{bw},{cdf},{load},{error_rate},{time},{timeout_slowstart_mode},{irn_rto_high},{irn_rto_low}\n".format(
            simulday=simulday,
            config_ID=config_ID,
            cc_mode=cc_mode,
            lb_mode=lb_mode,
            ar_mode=ar_mode,
            cwh_tx_expiry_time=cwh_tx_expiry_time,
            cwh_extra_reply_deadline=cwh_extra_reply_deadline,
            cwh_path_pause_time=cwh_path_pause_time,
            cwh_extra_voq_flush_time=cwh_extra_voq_flush_time,
            cwh_default_voq_waiting_time=cwh_default_voq_waiting_time,
            pfc=enabled_pfc,
            irn=loss_recovery_mode,
            has_win=has_win,
            var_win=var_win,
            window_size=window_size,
            topo=topo,
            bw=bw,
            cdf=cdf,
            load=netload,
            error_rate=args.error_rate,
            time=args.simul_time,
            timeout_slowstart_mode=args.timeout_slowstart_mode,
            irn_rto_high=irn_rto_high,
            irn_rto_low=irn_rto_low
        )
        history.write(history_row)
        history.flush()
        fcntl.flock(history, fcntl.LOCK_UN)
    artifact_history_file = os.environ.get("ARTIFACT_HISTORY_FILE")
    if artifact_history_file:
        append_history(artifact_history_file, history_row)
    append_runtime_manifest(config_ID)
    # MODIFICATION END

    # 1 BDP calculation
    if topo2bdp.get(topo) == None:
        print("ERROR - topology is not registered in run.py!!", flush=True)
        return
    bdp = int(topo2bdp[topo])
    print("1BDP = {}".format(bdp))

    # DCQCN ECN threshold parameters - bandwidth-specific settings
    # Fixed thresholds for different bandwidth tiers to avoid calculation errors
    if bw >= 400:  # 400G network
        kmax_threshold = 1600  # 4x scaling for 400G
        kmin_threshold = 400
        print(f"ECN thresholds for 400G: KMAX={kmax_threshold}, KMIN={kmin_threshold} packets")
    elif bw >= 200:  # 200G network
        kmax_threshold = 800   # 2x scaling for 200G
        kmin_threshold = 200
        print(f"ECN thresholds for 200G: KMAX={kmax_threshold}, KMIN={kmin_threshold} packets")
    else:  # 100G and below
        kmax_threshold = 400   # Original values for 100G
        kmin_threshold = 100
        # kmax_threshold = 160000  # 4x scaling for 400G
        # kmin_threshold = 40000
        print(f"ECN thresholds for 100G: KMAX={kmax_threshold}, KMIN={kmin_threshold} packets")

    # ECN marking probability from command line argument
    # ecn_pmax_prob = args.ecn_pmax
    ecn_pmax_prob = 0.2
    print(f"ECN marking probability (PMAX): {ecn_pmax_prob}")

    kmax_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
        bw*200000000, kmax_threshold, bw*500000000, kmax_threshold, bw*1000000000, kmax_threshold,
        bw*2*1000000000, kmax_threshold, bw*2500000000, kmax_threshold, bw*4*1000000000, kmax_threshold)
    kmin_map = "6 %d %d %d %d %d %d %d %d %d %d %d %d" % (
        bw*200000000, kmin_threshold, bw*500000000, kmin_threshold, bw*1000000000, kmin_threshold,
        bw*2*1000000000, kmin_threshold, bw*2500000000, kmin_threshold, bw*4*1000000000, kmin_threshold)
    pmax_map = "6 %d %d %d %d %d %.2f %d %.2f %d %.2f %d %.2f" % (
        bw*200000000, ecn_pmax_prob, bw*500000000, ecn_pmax_prob, bw*1000000000, ecn_pmax_prob,
        bw*2*1000000000, ecn_pmax_prob, bw*2500000000, ecn_pmax_prob, bw*4*1000000000, ecn_pmax_prob)

    # queue monitoring
    qlen_mon_start = flowgen_start_time
    qlen_mon_end = flowgen_stop_time

    # MODIFICATION START: Handle 'none' CC mode and set enable_qcn flag
    if (cc_mode == 1 or cc_mode == 2 or cc_mode == 4 or cc_mode == 5):  # DCQCN, DCQCN_DST, DCQCN_LANE, or NONE
        # DCQCN parameter settings based on literature
        # NOTE: Research shows DCQCN has challenges at 400G speeds
        # These parameters follow the original DCQCN design but may need empirical tuning
        ai = 10 * bw / 25   # Original formula from SIGCOMM'15 paper
        hai = 25 * bw / 25  # Original formula maintains constant ratio
        ewma_gain = 0.00390625  # Standard EWMA gain (1/256)

        # TODO: For 400G networks, consider alternative CC algorithms (HPCC, Spectrum-X)
        # as DCQCN has known performance issues at very high speeds

        dctcp_ai = 1000
        fast_react = 0
        mi = 0
        int_multi = 1
        enable_qcn_flag = 0 if args.cc == 'none' else 1

        # Generate AlltoallV message sizes file if needed
        ai_message_sizes_file = "none"
        if workload_type == 5:  # AlltoallV
            # Generate groups based on user specification
            group_size = args.ai_nodes_per_group
            num_groups = max(1, n_host // group_size)
            groups = []
            for g in range(num_groups):
                group = list(range(g * group_size, min((g + 1) * group_size, n_host)))
                groups.append(group)

            # Generate message sizes for each group
            message_sizes_per_group = []
            for group in groups:
                group_message_sizes = generate_alltoallv_message_sizes(
                    args.netload_pattern, ai_message_size, len(group))
                message_sizes_per_group.append(group_message_sizes)

            # Save to file
            ai_message_sizes_file = save_alltoallv_message_sizes(
                config_ID, groups, message_sizes_per_group)
            print(f"Generated AlltoallV message sizes: {ai_message_sizes_file}")

        config = config_template.format(id=config_ID, topo=topo, flow=flow,
                                    workload_type=workload_type, ai_message_size=ai_message_size,
                                    ai_message_sizes_file=ai_message_sizes_file, ai_nodes_per_group=args.ai_nodes_per_group, num_rounds=num_rounds,
                                    qlen_mon_start=qlen_mon_start, qlen_mon_end=qlen_mon_end, flowgen_start_time=flowgen_start_time,
                                    flowgen_stop_time=flowgen_stop_time, sw_monitoring_interval=sw_monitoring_interval,
                                    load=netload, buffer_size=buffer, lb_mode=lb_mode, ar_mode=ar_mode, cwh_tx_expiry_time=cwh_tx_expiry_time,
                                    cwh_extra_reply_deadline=cwh_extra_reply_deadline, cwh_default_voq_waiting_time=cwh_default_voq_waiting_time,
                                    cwh_path_pause_time=cwh_path_pause_time, cwh_extra_voq_flush_time=cwh_extra_voq_flush_time,
                                    enabled_pfc=enabled_pfc, enabled_irn=enabled_irn_flag, enabled_dcp=enabled_dcp_flag,
                                    enabled_ideal=enabled_ideal_flag, enabled_dcp_ack_opt=enabled_dcp_ack_opt_flag,
                                    cc_mode=cc_mode,
                                    lanes_per_destination=lanes_per_destination,
                                    ai=ai, hai=hai, dctcp_ai=dctcp_ai,
                                    has_win=has_win, var_win=var_win, window_size=window_size,
                                    fast_react=fast_react, mi=mi, int_multi=int_multi, ewma_gain=ewma_gain,
                                    kmax_map=kmax_map, kmin_map=kmin_map, pmax_map=pmax_map, error_rate=args.error_rate,
                                    timeout_slowstart_mode=args.timeout_slowstart_mode,
                                    enable_qcn=enable_qcn_flag,
                                    rp_timer=args.rp_timer,
                                    rate_decrease_interval=args.rate_decrease_interval,
                                    irn_rto_high=irn_rto_high,
                                    irn_rto_low=irn_rto_low)
    else:
        print("unknown cc:{}".format(args.cc))
        config = "" # Or handle this case appropriately
    # MODIFICATION END

    with open(config_name, "w") as file:
        file.write(config)

    # run program
    print("Running simulation...")
    output_log = config_name.replace(".txt", ".log")
    simulator, run_command = simulator_command(config_name, output_log)
    append_history(
        "./mix/.history",
        run_command + "\n"
        + "./waf --run 'network-load-balance' --command-template='gdb --args %s {config_name}'\n".format(
            config_name=config_name
        )
        + "\n",
    )

    print(run_command)
    simulation_status = run_simulator(simulator, run_command, output_log)
    if simulation_status != 0:
        raise RuntimeError(
            "Simulation failed for config {} with wait status {}".format(
                config_ID, simulation_status
            )
        )

    ####################################################
    #                 Analyze the output FCT           #
    ####################################################
    # NOTE: collect data except warm-up and cold-finish period
    fct_analysis_time_limit_begin = int(
        flowgen_start_time * 1e9) + int(0.005 * 1e9)  # warmup
    fct_analysistime_limit_end = int(
        flowgen_stop_time * 1e9) + int(10.0 * 1e9)  # extra term

    print("Analyzing output FCT...")
    print("python3 fctAnalysis.py -id {config_ID} -dir {dir} -bdp {bdp} -sT {fct_analysis_time_limit_begin} -fT {fct_analysistime_limit_end} > /dev/null 2>&1".format(
        config_ID=config_ID, dir=os.getcwd(), bdp=bdp, fct_analysis_time_limit_begin=fct_analysis_time_limit_begin, fct_analysistime_limit_end=fct_analysistime_limit_end))
    os.system("python3 fctAnalysis.py -id {config_ID} -dir {dir} -bdp {bdp} -sT {fct_analysis_time_limit_begin} -fT {fct_analysistime_limit_end} > /dev/null 2>&1".format(
        config_ID=config_ID, dir=os.getcwd(), bdp=bdp, fct_analysis_time_limit_begin=fct_analysis_time_limit_begin, fct_analysistime_limit_end=fct_analysistime_limit_end))

    if lb_mode == 9: # ConWeave Logging
        ################################################################
        #             Analyze hardware resource of ConWeave            #
        ################################################################
        # NOTE: collect data except warm-up and cold-finish period
        queue_analysis_time_limit_begin = int(
            flowgen_start_time * 1e9) + int(0.005 * 1e9)  # warmup
        queue_analysistime_limit_end = int(flowgen_stop_time * 1e9)
        print("Analyzing output Queue...")
        print("python3 queueAnalysis.py -id {config_ID} -dir {dir} -sT {queue_analysis_time_limit_begin} -fT {queue_analysistime_limit_end} > /dev/null 2>&1".format(
            config_ID=config_ID, dir=os.getcwd(), queue_analysis_time_limit_begin=queue_analysis_time_limit_begin, queue_analysistime_limit_end=queue_analysistime_limit_end))
        os.system("python3 queueAnalysis.py -id {config_ID} -dir {dir} -sT {queue_analysis_time_limit_begin} -fT {queue_analysistime_limit_end} > /dev/null 2>&1".format(
            config_ID=config_ID, dir=os.getcwd(), queue_analysis_time_limit_begin=queue_analysis_time_limit_begin, queue_analysistime_limit_end=queue_analysistime_limit_end,
            monitoringInterval=sw_monitoring_interval))

    print("\n\n============== Done ============== ")


if __name__ == "__main__":
    main()
