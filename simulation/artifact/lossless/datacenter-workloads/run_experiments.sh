#!/bin/bash

# ==============================================================================
# Lossless datacenter workloads: Figure 4, Figure 5, Figure 6, and Table 4
#
# This runner intentionally follows autorun_new.sh. To change an experiment,
# edit the complete run_experiment_group line in "Experiment list" below.
# ==============================================================================


# -------------------- Paths --------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
LOG_DIR="${SCRIPT_DIR}/results/logs"
HISTORY_FILE="${SCRIPT_DIR}/results/lossless_datacenter.history"


# -------------------- Global configuration --------------------

# Maximum number of run.py simulations on the server.
MAX_JOBS=60

# Same process pattern used by autorun_new.sh for global concurrency control.
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"

# Fixed parameters shared by all experiments below.
RUNTIME="0.05"
FLOWGEN="src"
NIC_BW="100"


# -------------------- Helper functions --------------------

cecho() {
    RED="\033[0;31m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    BLUE="\033[0;34m"
    NC="\033[0m"
    printf "${!1}${2}${NC}\n"
}


# Wait for a global slot, then execute the command in the background.
run_if_slot_free() {
    local log_file=$1
    shift

    while [ "$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")" -ge "$MAX_JOBS" ]; do
        local current_system_procs
        current_system_procs=$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")
        printf "\r$(cecho "YELLOW" "System processes (${current_system_procs}) reached ${MAX_JOBS}; waiting...")"
        sleep 1
    done
    printf "%-100s\r" " "

    "$@" > "$log_file" 2>&1 &
    sleep 1
}


# Parameter order:
#   1  topology
#   2  network load
#   3  error rate
#   4  workload/CDF
#   5  congestion control
#   6  PFC
#   7  IRN/loss-recovery mode
#   8  adaptive-routing mode
#   9  timeout slow-start mode
#   10 window size
#   11 RTO high (us)
#   12 RTO low (us)
#   13 buffer size (MB; 0 selects the simulator's default shared buffer)
#   14... load-balancing algorithms
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
    shift 13
    local lbs=("$@")

    cecho "GREEN" "Submit: TOPO=${topology} LOAD=${netload} CDF=${cdf} CC=${cc} PFC=${pfc} IRN=${irn} ARMODE=${armode} TIMEOUT=${timeout_mode} WIN=${win_size} RTO=${rto_high}/${rto_low} BUFFER=${buffer_size} LBs=${lbs[*]}"

    for lb in "${lbs[@]}"; do
        local log_filename="${LOG_DIR}/topo=${topology}_load=${netload}_err=${error_rate}_cdf=${cdf}_cc=${cc}_pfc=${pfc}_irn=${irn}_armode=${armode}_timeout=${timeout_mode}_win=${win_size}_rtoh=${rto_high}_rtol=${rto_low}_buf=${buffer_size}_lb=${lb}.log"
        RUN_LOGS+=("$log_filename")

        run_if_slot_free "$log_filename" python3 run.py \
            --cc "$cc" \
            --lb "$lb" \
            --pfc "$pfc" \
            --irn "$irn" \
            --armode "$armode" \
            --simul_time "$RUNTIME" \
            --netload "$netload" \
            --topo "$topology" \
            --cdf "$cdf" \
            --error_rate "$error_rate" \
            --flowgen_mode "$FLOWGEN" \
            --timeout_slowstart_mode "$timeout_mode" \
            --windowSize "$win_size" \
            --rto_high "$rto_high" \
            --rto_low "$rto_low" \
            --buffer "$buffer_size" \
            --bw "$NIC_BW"
    done
}


# ==============================================================================
# Experiment list
#
# Each line contains every varying run.py parameter. The two lines under each
# scenario only differ in armode and the listed load-balancing algorithms.
# ==============================================================================

cd "$NS3_ROOT" || exit 1
mkdir -p "$LOG_DIR"
RUN_LOGS=()

cecho "BLUE" "=================================================="
cecho "BLUE" "Submitting lossless datacenter experiments"
cecho "BLUE" "=================================================="

# Figure 4(a), Figure 5, Figure 6 (AliStorage), Table 4
# topology                         load  error    workload         cc       pfc irn armode timeout window  rtoH rtoL buffer LBs
run_experiment_group "leaf_spine_128_100G_OS2"    "80" "0.000" "AliStorage2019" "dcqcn"  1   0   noar   0       104000  4000 4000 0      fecmp conweave
run_experiment_group "leaf_spine_128_100G_OS2"    "80" "0.000" "AliStorage2019" "dcqcn"  1   0   ar     0       104000  4000 4000 0      drill rps adaptive

# Figure 4(b)
# topology                         load  error    workload         cc       pfc irn armode timeout window  rtoH rtoL buffer LBs
run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "AliStorage2019" "dcqcn"  1   0   noar   0       156000  4000 4000 0      fecmp conweave
run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "AliStorage2019" "dcqcn"  1   0   ar     0       156000  4000 4000 0      drill rps adaptive

# Figure 6 (Solar)
# topology                         load  error    workload         cc       pfc irn armode timeout window  rtoH rtoL buffer LBs
run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "Solar2022"      "dcqcn"  1   0   noar   0       156000  4000 4000 0      fecmp conweave
run_experiment_group "fat_k8_100G_OS1"            "80" "0.000" "Solar2022"      "dcqcn"  1   0   ar     0       156000  4000 4000 0      drill rps adaptive

# Figure 6 (Hadoop)
# topology                         load  error    workload         cc       pfc irn armode timeout window  rtoH rtoL buffer LBs
run_experiment_group "leaf_spine_L8_S16_100G_OS1" "80" "0.000" "FbHdp2015"      "dcqcn"  1   0   noar   0       104000  4000 4000 0      fecmp conweave
run_experiment_group "leaf_spine_L8_S16_100G_OS1" "80" "0.000" "FbHdp2015"      "dcqcn"  1   0   ar     0       104000  4000 4000 0      drill rps adaptive


# -------------------- Wait and collect parser history --------------------

cecho "GREEN" "All experiment groups submitted; waiting for background jobs..."
wait

: > "$HISTORY_FILE"
for log_file in "${RUN_LOGS[@]}"; do
    config_id=$(sed -n 's#.*Config filename:.*/mix/output/\([^/]*\)/config.txt.*#\1#p' "$log_file" | tail -n 1)
    if [ -z "$config_id" ]; then
        cecho "RED" "Cannot find config ID in ${log_file}"
        exit 1
    fi
    awk -F, -v id="$config_id" '$2 == id {print; exit}' mix/.history >> "$HISTORY_FILE"
done

cecho "BLUE" "=================================================="
cecho "BLUE" "All experiments finished"
cecho "BLUE" "History: ${HISTORY_FILE}"
cecho "BLUE" "Next: ${SCRIPT_DIR}/parse_results.sh"
cecho "BLUE" "=================================================="
