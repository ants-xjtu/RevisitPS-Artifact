#!/bin/bash

# ==============================================================================
#                 AI Collectives Experimentation & Management Script (v3)
# ==============================================================================
#
# Features:
#   - 支持所有AI集体通信工作负载: Alltoall, RingAllreduce, TreeAllreduce, TreeAllreduceChunked, AlltoallV
#   - [NEW] AlltoallV支持多种消息大小模式: uniform/power2/linear/random
#   - [NEW] 自动根据拓扑设置窗口大小 (fat-tree: 156000, leaf-spine: 104000)
#   - [NEW] 支持最新的RTO参数 (--rto_high, --rto_low)
#   - 支持组合实验: 拓扑 × 消息大小 × 工作负载类型 × 拥塞控制算法
#   - 全局并发控制，防止服务器过载
#   - 彩色日志输出，易于跟踪实验进度
#   - 每个run.py实例的输出保存到独立的日志文件
#
# ==============================================================================
#
# 工作负载参数说明:
#
# 1. Alltoall: 传统全对全通信
#    - 参数: --cdf Alltoall --netload <消息大小>
#    - 示例: python3 run.py --cdf Alltoall --netload 1048576
#
# 2. RingAllreduce: 环形All-Reduce
#    - 参数: --cdf RingAllreduce --netload <消息大小>
#    - 示例: python3 run.py --cdf RingAllreduce --netload 1048576
#
# 3. TreeAllreduce: 树形All-Reduce
#    - 参数: --cdf TreeAllreduce --netload <消息大小>
#    - 示例: python3 run.py --cdf TreeAllreduce --netload 1048576
#
# 4. TreeAllreduceChunked: 分块树形All-Reduce (适合大消息)
#    - 参数: --cdf TreeAllreduceChunked --netload <消息大小>
#    - 示例: python3 run.py --cdf TreeAllreduceChunked --netload 19660800
#
# 5. AlltoallV: 变长全对全通信
#    - 参数: --cdf AlltoallV --netload <基础消息大小> --netload_pattern <模式>
#    - 新流量模式:
#      * uniform: Mode 1 - 每个GPU发送相同总量，均匀分布到其他GPU
#      * zipfian: Mode 2 - 每个GPU发送相同总量，但按Zipfian分布(α=0.8)产生大象流和老鼠流
#      * moe: Mode 3 - MoE Incast模式，发送端均匀，接收端按Zipfian分布产生incast流量
#    - 传统模式(向后兼容):
#      * power2: 按2的幂次增长 (base*2^(i%4))
#      * linear: 线性增长 (base*(1+i/total))
#      * random: 随机大小 (base的0.25-4倍)
#    - 示例: python3 run.py --cdf AlltoallV --netload 1048576 --netload_pattern zipfian
#
# 其他重要参数:
# - --cc: 拥塞控制 (none/dcqcn/hpcc/timely)
# - --lb: 负载均衡 (rps/drill/adaptive/fecmp/letflow/conga/conweave)
# - --pfc: PFC开关 (0/1)
# - --irn: IRN模式 (0/1/2/3/4)
# - --armode: 自适应路由 (noar/ar/arsp)
# - --windowSize: 窗口大小 (0表示无窗口)
# - --topo: 拓扑文件名
#
# ==============================================================================


# -------------------- Helper Functions --------------------

# Color output function to beautify and differentiate log message types
# Usage: cecho "COLOR" "Message"
# Example: cecho "GREEN" "Success!"
cecho() {
    RED="\033[0;31m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    BLUE="\033[0;34m"
    NC="\033[0m" # No Color
    printf "${!1}${2}${NC}\n"
}


# -------------------- Global Configuration --------------------

# ⭐ Global maximum number of concurrent jobs (total 'run.py' processes running on the entire server)
MAX_JOBS=45

# ⭐ [CRITICAL CONFIG] Process pattern for global concurrency control
#     This pattern is used with 'pgrep' to count matching processes across the entire system
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"

# ⭐ [EXPERIMENT PARAMETERS] Define all variable experiment parameters here
# The script will automatically run a full combination of all arrays below
TOPOLOGIES=(
    # bigswitch_H128_100G_OS1
    # bigswitch_H8_100G_OS1
    "leaf_spine_L8_S16_100G_OS1"
    # --- Asymmetric leaf-spine topologies (from autorun_asy.sh) ---
    # "leafspine_L8_S16_100G_AsymFail1pct_OS1"
    # "leafspine_L8_S16_100G_AsymFail10pct_OS1"
    # "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1"
    # "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1"
    # "fat_k8_100G_OS2"
    "fat_k8_100G_OS1"
)

# ⭐ NETLOADS 现在表示「每个节点每轮的目标总接收字节数」(per-node total recv)。
# 实际 --netload (per-flow message_size) 在循环内根据 CDF 与 N=ai_nodes_per_group 动态推导：
#   - AlltoallV     : --netload = TARGET           (矩阵里 max recv = TARGET)
#   - Alltoall      : --netload = TARGET / (N-1)
#   - RingAllreduce : --netload = TARGET / (2*(N-1))
#   - TreeAllreduce / TreeAllreduceChunked : --netload = TARGET (自行调整)
NETLOADS=(
    # "8000"
    # "32000"
    # "128000"
    # "512000"
    # "1024000"
    # "4096000"
    # "8192000"
    # "16384000"
    # "32768000"
    "157286400"    # 150 MB = 150*1024*1024 (每节点目标接收量)
    # "161432745"  # 旧值 ~154 MB
    # "183654540"
    # "137625600"
    # "19660800"
)

# ⭐ AI Nodes Per Group Configuration
AI_NODES_PER_GROUP=(
    8    # 16 groups x 8 nodes (original)
    16   # 8 groups x 16 nodes
    32   # 4 groups x 32 nodes
    64   # 2 groups x 32 nodes
    128   # 2 groups x 32 nodes
)

# ⭐ AI Workload Types - 支持所有AI工作负载
CDFS=(
    "Alltoall"
    "RingAllreduce"
    # "TreeAllreduce"
    # "TreeAllreduceChunked"
    "AlltoallV"
)

# ⭐ AlltoallV Message Size Patterns
NETLOAD_PATTERNS=(
    # "uniform"
    # "power2"
    # "linear"
    # "random"
    # "incast"
    # "zipfian"
    "zipfian_incast"
    # "moe"
)

# ⭐ [NEW] Congestion Control Algorithms
CCS=(
    # "dcqcn"
    "none"
)


# Fixed Experiment Parameters
RUNTIME="0.05"
FLOWGEN="src"
# Fixed error rate to 0 to focus on performance in an ideal network
FIXED_ERROR_RATE="0.0"
# RTO parameters
RTO_HIGH="320"
RTO_LOW="100"
# Buffer size (MB)
BUFFER_SIZE="0.5"


# -------------------- Core Concurrency Control Function --------------------

# Function to run a task (throttled based on system-wide process count)
# This function waits until a free "slot" is available in the system before executing the command in the background
run_if_slot_free() {
    # Use pgrep to check the total number of processes matching the pattern system-wide
    while [ "$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")" -ge "$MAX_JOBS" ]; do
        local current_system_procs=$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")
        printf "\r$(cecho "YELLOW" "System process count (${current_system_procs}) has reached the limit of ${MAX_JOBS}. Waiting for resources...")"
        sleep 1
    done
    printf "%-100s\r" " "

    # Once a slot is free, execute the actual command in the background
    "$@" &
    sleep 1
}


# -------------------- Experiment Group Submission Function --------------------

# Run an experiment group
run_experiment_group() {
    local topology=$1
    local netload=$2
    local error_rate=$3
    local cdf=$4
    local cc=$5
    local pfc=$6
    local irn=$7
    local armode=$8
    local timeout_mode=$9
    local win_size=${10}
    local rto_high=${11}
    local rto_low=${12}
    local buffer_size=${13}
    local ai_nodes_per_group=${14}
    shift 14
    local lbs=("$@")

    # Log shows all parameters
    cecho "GREEN" "   -> Submitting group: CDF=$cdf CC=$cc PFC=$pfc IRN=$irn ARMODE=$armode TIMEOUT=${timeout_mode} WIN_SIZE=${win_size} RTO_H=${rto_high} RTO_L=${rto_low} BUFFER=${buffer_size} AI_NODES_PER_GROUP=${ai_nodes_per_group} LBs=${lbs[*]}"

    for lb in "${lbs[@]}"; do
        # For AlltoallV, iterate through netload patterns; for others, use single pattern
        if [[ "$cdf" == "AlltoallV" ]]; then
            patterns=("${NETLOAD_PATTERNS[@]}")
        else
            patterns=("none")  # netload_pattern不适用于其他workload
        fi

        for pattern in "${patterns[@]}"; do
            # Create a unique log file name
            if [[ "$cdf" == "AlltoallV" ]]; then
                local log_file="logs/run_${cdf}_${netload}_${pattern}_g${ai_nodes_per_group}_${cc}_${lb}_pfc${pfc}_irn${irn}_ar${armode}.log"
            else
                local log_file="logs/run_${cdf}_${netload}_g${ai_nodes_per_group}_${cc}_${lb}_pfc${pfc}_irn${irn}_ar${armode}.log"
            fi

            # Build command with all parameters
            local cmd="python3 run.py \
                --cc '$cc' --lb '$lb' --pfc '$pfc' --irn '$irn' --armode '$armode' \
                --simul_time '$RUNTIME' --netload '$netload' --topo '$topology' \
                --cdf '$cdf' --error_rate '$error_rate' --flowgen_mode '$FLOWGEN' \
                --timeout_slowstart_mode '$timeout_mode' \
                --windowSize '$win_size' \
                --rto_high '$rto_high' --rto_low '$rto_low' \
                --buffer '$buffer_size' --ai_nodes_per_group '$ai_nodes_per_group'"

            # Add netload_pattern ONLY for AlltoallV workloads
            if [[ "$cdf" == "AlltoallV" ]]; then
                cmd="$cmd --netload_pattern '$pattern'"
            fi

            # Call the concurrency controller and redirect output to the log file
            run_if_slot_free bash -c "$cmd > '$log_file' 2>&1"
        done
    done
}


# ==============================================================================
#                      Main Script Execution Logic
# ==============================================================================

cecho "BLUE" "=================================================="
cecho "BLUE" "      Starting submission of AI collective communication experiment tasks"
cecho "BLUE" "=================================================="
cecho "YELLOW" "Global Concurrency Limit (MAX_JOBS): ${MAX_JOBS}"
cecho "YELLOW" "Monitoring Process Pattern: '${PROCESS_PATTERN_TO_MONITOR}'"
cecho "YELLOW" "----------------------------------"

# Ensure the log directory exists
mkdir -p logs
cecho "YELLOW" "All logs will be saved in the 'logs/' directory."
cecho "YELLOW" "----------------------------------"


# Using nested loops to iterate through AI experiment parameter combinations
for topo in "${TOPOLOGIES[@]}"; do
    # ==================== 根據拓撲自動設定窗口大小 ====================
    default_win_size=0
    if [[ "$topo" == *"fat"* ]]; then
        # default_win_size=156000
        default_win_size=156000
    elif [[ "$topo" == *"leaf_spine"* ]] || [[ "$topo" == *"leafspine"* ]]; then
        default_win_size=104000
        # default_win_size=512000
    fi
    cecho "YELLOW" "檢測到拓撲 '${topo}'，設定默認 win_size 為 ${default_win_size}"

    for load in "${NETLOADS[@]}"; do
        for cdf in "${CDFS[@]}"; do
            # CC 不再循環 — 請在每個 run_experiment_group 調用中顯式指定 CC (dcqcn/hpcc/timely/dcqcn_lane/...)
                for ai_nodes_per_group in "${AI_NODES_PER_GROUP[@]}"; do
                    # ===== 根据 CDF 推导 effective_n 与 actual_load =====
                    # 目标：每节点每轮总接收量 == $load 字节
                    # 注意：effective_n 同时决定 (1) actual_load 公式 (2) 传给 run.py 的
                    #        --ai_nodes_per_group (main.cc 用它作为 num_node_per_g 分组)
                    #   AlltoallV     : effective_n = ai_nodes_per_group, actual_load = load
                    #   Alltoall      : effective_n = 8 (固定),           actual_load = load / (N-1)
                    #   RingAllreduce : effective_n = 8 (固定),           actual_load = load / (2*(N-1))
                    #   其他          : effective_n = ai_nodes_per_group, actual_load = load
                    if [[ "$cdf" == "Alltoall" || "$cdf" == "RingAllreduce" ]]; then
                        # 工作负载语义固定 8 节点一组；AI_NODES_PER_GROUP 多值时仅跑一次去重
                        if [[ "$ai_nodes_per_group" != "${AI_NODES_PER_GROUP[0]}" ]]; then
                            continue
                        fi
                        effective_n=8
                        if [[ "$cdf" == "Alltoall" ]]; then
                            actual_load=$(( load / (effective_n - 1) ))
                        else
                            actual_load=$(( load / (2 * (effective_n - 1)) ))
                        fi
                    else
                        effective_n=$ai_nodes_per_group
                        actual_load="$load"
                    fi
                    cecho "BLUE" "=====>> Processing: TOPO=[${topo}], TARGET_RECV=[${load}B], CDF=[${cdf}], N=[${effective_n}], ACTUAL_NETLOAD=[${actual_load}B] <<====="

                    # -------------------- 各种AI工作负载的实验示例 --------------------
                    # NOTE: run_experiment_group parameter order:
                    # 1:topo, 2:load, 3:err_rate, 4:cdf, 5:cc, 6:pfc, 7:irn, 8:armode,
                    # 9:timeout, 10:winsize, 11:rto_high, 12:rto_low, 13:buffer_size, 14:ai_nodes_per_group, 后面跟着所有 lb 模式
                    #
                    # IMPORTANT: netload_pattern 参数是AI workload独有的，只对AlltoallV有效:
                    # - AlltoallV: 会自动测试 uniform/power2/linear/random 4种模式
                    # - 其他workload: 忽略netload_pattern参数

                    # =========================== AlltoallV Examples ===========================
                    if [[ "$cdf" == "AlltoallV" ]]; then
                        # AlltoallV with different load balancing algorithms (会自动测试所有pattern)
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 0 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # Lossless
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 noar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" fecmp letflow conga conweave
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # # Lossy
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 noar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" fecmp letflow conga conweave
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 2 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 2 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 1 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 2 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 4 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 8 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 16 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 32 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 64 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 128 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive                       
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 2 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 1 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive

                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 1 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 2 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 4 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 8 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 16 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 32 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 64 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 128 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive

                    # =========================== TreeAllreduce Examples ========================
                    elif [[ "$cdf" == "TreeAllreduce" ]]; then
                        # TreeAllreduce experiments
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 0 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive

                    # =========================== TreeAllreduceChunked Examples ==============
                    elif [[ "$cdf" == "TreeAllreduceChunked" ]]; then
                        # TreeAllreduceChunked experiments (good for large messages)
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 0 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive

                    # =========================== Alltoall Examples =========================
                    # (N=effective_n=8, per-flow message_size ≈ 21.4 MB, 每节点收 150 MB)
                    elif [[ "$cdf" == "Alltoall" ]]; then
                        # --- Scenario 1: IRN RDMA (pfc=0, irn=1) ---
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 noar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" fecmp conga conweave
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 0 2 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 0 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive

                        # --- Scenario 2: Lossless RDMA (pfc=1, irn=0) ---
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 noar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" fecmp conga conweave
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive

                    # =========================== RingAllreduce Examples ====================
                    # (N=effective_n=8, per-flow message_size ≈ 10.7 MB, 每节点收 150 MB)
                    elif [[ "$cdf" == "RingAllreduce" ]]; then
                        # --- Scenario 1: IRN RDMA (pfc=0, irn=1) ---
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 noar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" fecmp conga conweave
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 2 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 0 1 ar 0 "$default_win_size" "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 0 1 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 0 2 ar 0 512000 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 0 1 ar 0 0 "$RTO_HIGH" "$RTO_LOW" "$BUFFER_SIZE" "$effective_n" rps drill adaptive

                        # --- Scenario 2: Lossless RDMA (pfc=1, irn=0) ---
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 noar 0 512000 4000 4000 "$BUFFER_SIZE" "$effective_n" fecmp conga conweave
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" dcqcn 1 0 ar 0 512000  4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        # run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 1 0 ar 0 "$default_win_size" 4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                        run_experiment_group "$topo" "$actual_load" "$FIXED_ERROR_RATE" "$cdf" none 1 0 ar 0 512000  4000 4000 "$BUFFER_SIZE" "$effective_n" rps drill adaptive
                    fi
                done      # ai_nodes_per_group loop
        done          # cdf loop
    done              # load loop
done                  # topo loop

cecho "GREEN" "=================================================="
cecho "GREEN" "All task combinations have been submitted to the background."
cecho "GREEN" "The script will now wait for all background tasks it started to complete..."
cecho "GREEN" "=================================================="

# CRITICAL STEP: Wait for all background tasks launched by *this script* to finish.
wait

cecho "BLUE" "=================================================="
cecho "BLUE" "         All background tasks have completed!"
cecho "BLUE" "=================================================="