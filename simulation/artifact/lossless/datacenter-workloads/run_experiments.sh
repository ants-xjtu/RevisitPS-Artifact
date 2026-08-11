#!/bin/bash

# ==============================================================================
# Lossless datacenter workloads: Figures 4--6, Figures 8--9, and Tables 4--5
#
# This runner intentionally follows autorun_new.sh. To change an experiment,
# edit the complete run_experiment_group line in "Experiment list" below.
# ==============================================================================


# -------------------- Paths --------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
COMMON_DIR="${NS3_ROOT}/artifact/common"
source "${COMMON_DIR}/run_tracking.sh"
if artifact_tracking_enabled; then
    LOG_DIR="${ARTIFACT_RUN_DIR}/logs"
    HISTORY_FILE="${ARTIFACT_RUN_DIR}/history/all.history"
    MANIFEST_FILE="${ARTIFACT_RUN_DIR}/manifest.csv"
else
    LOG_DIR="${SCRIPT_DIR}/results/logs"
    HISTORY_FILE="${SCRIPT_DIR}/results/lossless_datacenter.history"
    MANIFEST_FILE="${SCRIPT_DIR}/results/lossless_datacenter_runs.csv"
fi


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


lb_label() {
    case "$1" in
        fecmp) echo "ECMP" ;;
        conweave) echo "ConWeave" ;;
        drill) echo "DRILL" ;;
        rps) echo "RPS" ;;
        adaptive) echo "AR" ;;
        *) echo "$1" ;;
    esac
}


# Wait for a global slot, then execute the command in the background.
run_if_slot_free() {
    local task_id=$1
    local log_file=$2
    shift 2

    while [ "$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")" -ge "$MAX_JOBS" ]; do
        local current_system_procs
        current_system_procs=$(pgrep -fc -- "$PROCESS_PATTERN_TO_MONITOR")
        printf "\r$(cecho "YELLOW" "System processes (${current_system_procs}) reached ${MAX_JOBS}; waiting...")"
        sleep 1
    done
    printf "%-100s\r" " "

    artifact_run_background "$task_id" "$log_file" "$@"
    sleep 1
}


# Parameter order:
#   1 recipe, 2 paper outputs, 3 topology, 4 network load, 5 error rate,
#   6 workload/CDF, 7 congestion control, 8 PFC, 9 IRN/loss recovery,
#   10 adaptive-routing mode, 11 timeout slow-start mode, 12 window size,
#   13 RTO high, 14 RTO low, 15 buffer size, 16... load-balancing algorithms.
run_experiment_group() {
    local recipe=$1
    local paper_outputs=$2
    local topology=$3
    local netload=$4
    local error_rate=$5
    local cdf=$6
    local cc=$7
    local pfc=$8
    local irn=$9
    local armode=${10}
    local timeout_mode=${11}
    local win_size=${12}
    local rto_high=${13}
    local rto_low=${14}
    local buffer_size=${15}
    shift 15
    local lbs=("$@")

    cecho "GREEN" "Submit: TOPO=${topology} LOAD=${netload} CDF=${cdf} CC=${cc} PFC=${pfc} IRN=${irn} ARMODE=${armode} TIMEOUT=${timeout_mode} WIN=${win_size} RTO=${rto_high}/${rto_low} BUFFER=${buffer_size} LBs=${lbs[*]}"

    for lb in "${lbs[@]}"; do
        local algorithm
        algorithm=$(lb_label "$lb")
        local task_id="${recipe}__${topology}__${cdf}__g1__${algorithm}__t${timeout_mode}"
        local log_filename="${LOG_DIR}/topo=${topology}_load=${netload}_err=${error_rate}_cdf=${cdf}_cc=${cc}_pfc=${pfc}_irn=${irn}_armode=${armode}_timeout=${timeout_mode}_win=${win_size}_rtoh=${rto_high}_rtol=${rto_low}_buf=${buffer_size}_lb=${lb}.log"
        run_if_slot_free "$task_id" "$log_filename" \
            artifact_run_command "$MANIFEST_FILE" "$task_id" "$recipe" \
            "$paper_outputs" "$topology" "$cdf" 1 "$algorithm" \
            "$timeout_mode" python3 run.py \
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
artifact_prepare_simulator "$NS3_ROOT" || exit 1
artifact_tracking_init lossless datacenter-workloads 28 || exit 1
artifact_result_files_init "$HISTORY_FILE" "$MANIFEST_FILE" || exit 1
mkdir -p "$LOG_DIR"

cecho "BLUE" "=================================================="
cecho "BLUE" "Submitting lossless datacenter experiments"
cecho "BLUE" "=================================================="

# Figure 4(a), Figure 5, Figure 6 (AliStorage), Table 4
# recipe       outputs                         topology                         load error   workload        cc     pfc irn armode timeout window  rtoH rtoL buffer LBs
run_experiment_group "f4a_base"   "figure4;figure5;figure6;table4" "leaf_spine_128_100G_OS2"    80   "0.000" AliStorage2019 dcqcn 1   0   noar   0       104000 4000 4000 0      fecmp conweave
run_experiment_group "f4a_packet" "figure4;figure5;figure6;table4" "leaf_spine_128_100G_OS2"    80   "0.000" AliStorage2019 dcqcn 1   0   ar     0       104000 4000 4000 0      drill rps adaptive

# Figure 4(b)
run_experiment_group "f4b_base"   "figure4" "fat_k8_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 noar 0 156000 4000 4000 0 fecmp conweave
run_experiment_group "f4b_packet" "figure4" "fat_k8_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 ar   0 156000 4000 4000 0 drill rps adaptive

# Figure 6 (Solar)
run_experiment_group "f6_rpc_base"   "figure6" "fat_k8_100G_OS1" 80 "0.000" Solar2022 dcqcn 1 0 noar 0 156000 4000 4000 0 fecmp conweave
run_experiment_group "f6_rpc_packet" "figure6" "fat_k8_100G_OS1" 80 "0.000" Solar2022 dcqcn 1 0 ar   0 156000 4000 4000 0 drill rps adaptive

# Figure 6 (Hadoop)
run_experiment_group "f6_hadoop_base"   "figure6" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" FbHdp2015 dcqcn 1 0 noar 0 104000 4000 4000 0 fecmp conweave
run_experiment_group "f6_hadoop_packet" "figure6" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" FbHdp2015 dcqcn 1 0 ar   0 104000 4000 4000 0 drill rps adaptive

# Figure 8 datacenter reference panels.
run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" FbHdp2015      dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive
run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" Solar2022      dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive
run_experiment_group "pfc_dcn_workloads" "figure8" "leaf_spine_L8_S16_100G_OS1" 80 "0.0" AliStorage2019 dcqcn 1 0 ar 0 104000 4096 4096 0 adaptive

# Figure 9 and Table 5: 1:1 leaf-spine AliStorage.
run_experiment_group "f9_t5_base"   "figure9;table5" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 noar 0 104000 4000 4000 0 fecmp conweave
run_experiment_group "f9_t5_packet" "figure9;table5" "leaf_spine_L8_S16_100G_OS1" 80 "0.000" AliStorage2019 dcqcn 1 0 ar   0 104000 4000 4000 0 drill rps adaptive


# -------------------- Wait for experiments --------------------

cecho "GREEN" "All experiment groups submitted; waiting for background jobs..."
task_failures=0
artifact_wait_for_tasks || task_failures=$?
if ((task_failures > 0)); then
    cecho "RED" "${task_failures} datacenter experiment(s) failed"
    artifact_tracking_finalize || true
    exit 1
fi

if artifact_tracking_enabled && ! artifact_tracking_finalize; then
    cecho "RED" "Datacenter run status is incomplete"
    exit 1
fi

cecho "BLUE" "=================================================="
cecho "BLUE" "All experiments finished"
cecho "BLUE" "History: ${HISTORY_FILE}"
cecho "BLUE" "Next: ${SCRIPT_DIR}/parse_results.sh"
cecho "BLUE" "=================================================="
