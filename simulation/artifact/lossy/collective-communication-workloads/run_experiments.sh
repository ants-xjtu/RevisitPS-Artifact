#!/bin/bash

# ==============================================================================
# Lossy collective-communication workloads: Figure 13
# Reference: autorun_ai.sh
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NS3_ROOT="$(cd "${ARTIFACT_DIR}/.." && pwd)"
source "${ARTIFACT_DIR}/common/run_tracking.sh"
if artifact_tracking_enabled; then
    RESULTS_DIR="${ARTIFACT_RUN_DIR}"
    LOG_DIR="${RESULTS_DIR}/logs"
    HISTORY_FILE="${RESULTS_DIR}/history/all.history"
    MANIFEST_FILE="${RESULTS_DIR}/manifest.csv"
else
    RESULTS_DIR="${ARTIFACT_DIR}/results/lossy/collective-communication-workloads"
    LOG_DIR="${RESULTS_DIR}/logs"
    HISTORY_FILE="${RESULTS_DIR}/extended.history"
    MANIFEST_FILE="${RESULTS_DIR}/extended_runs.csv"
fi

MAX_JOBS=45
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"
RUNTIME="0.05"
FLOWGEN="src"
AI_LEAF_TOPOLOGY="leaf_spine_L8_S16_400G_OS1"
AI_FAT_TOPOLOGY="fat_k8_400G_OS1"
AI_LEAF_WINDOW=404000
AI_FAT_WINDOW=606000
AI_RING_WINDOW=1024000

cecho() {
    RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
    BLUE="\033[0;34m"; NC="\033[0m"
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

rate_decrease_interval_override() {
    local cdf=$1 group_size=$2 lb=$3
    if [[ "$cdf" == "AlltoallV" && "$group_size" -ge 32 && ( "$lb" == "fecmp" || "$lb" == "conweave" ) ]]; then
        echo 200
    fi
}

run_if_slot_free() {
    local task_id=$1 log_file=$2
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
#   1 recipe, 2 paper outputs, 3 topology, 4 netload, 5 error rate,
#   6 workload, 7 CC, 8 PFC, 9 IRN, 10 armode, 11 timeout,
#   12 window, 13 RTO high, 14 RTO low, 15 buffer, 16 bandwidth,
#   17 AI nodes/group, 18 AlltoallV pattern (none for other workloads),
#   19... load-balancing algorithms.
run_experiment_group() {
    local recipe=$1 paper_outputs=$2 topology=$3 netload=$4 error_rate=$5 cdf=$6
    local cc=$7 pfc=$8 irn=$9 armode=${10} timeout_mode=${11}
    local win_size=${12} rto_high=${13} rto_low=${14}
    local buffer_size=${15} bandwidth=${16}
    local ai_nodes_per_group=${17} pattern=${18}
    shift 18
    local lbs=("$@")

    cecho "GREEN" "Submit: RECIPE=${recipe} TOPO=${topology} CDF=${cdf} N=${ai_nodes_per_group} CC=${cc} PFC=${pfc} IRN=${irn} TIMEOUT=${timeout_mode} LBs=${lbs[*]}"
    for lb in "${lbs[@]}"; do
        local algorithm
        algorithm=$(lb_label "$lb")
        local task_id="${recipe}__${topology}__${cdf}__g${ai_nodes_per_group}__${algorithm}__t${timeout_mode}"
        local log_file="${LOG_DIR}/${task_id}.log"
        local command=(
            python3 run.py
            --cc "$cc" --lb "$lb" --pfc "$pfc" --irn "$irn" --armode "$armode"
            --simul_time "$RUNTIME" --netload "$netload" --topo "$topology"
            --cdf "$cdf" --error_rate "$error_rate" --flowgen_mode "$FLOWGEN"
            --timeout_slowstart_mode "$timeout_mode" --windowSize "$win_size"
            --rto_high "$rto_high" --rto_low "$rto_low"
            --buffer "$buffer_size" --bw "$bandwidth"
            --ai_nodes_per_group "$ai_nodes_per_group"
        )
        if [[ "$cdf" == "AlltoallV" ]]; then
            command+=(--netload_pattern "$pattern")
        fi
        local rate_decrease_interval
        rate_decrease_interval=$(rate_decrease_interval_override "$cdf" "$ai_nodes_per_group" "$lb")
        if [[ -n "$rate_decrease_interval" ]]; then
            command+=(--rate_decrease_interval "$rate_decrease_interval")
        fi
        run_if_slot_free "$task_id" "$log_file" \
            artifact_run_command "$MANIFEST_FILE" "$task_id" "$recipe" \
            "$paper_outputs" "$topology" "$cdf" "$ai_nodes_per_group" \
            "$algorithm" "$timeout_mode" "${command[@]}"
    done
}

cd "$NS3_ROOT" || exit 1
artifact_tracking_init lossy collective-communication-workloads 47 || exit 1
artifact_result_files_init "$HISTORY_FILE" "$MANIFEST_FILE" || exit 1
mkdir -p "$LOG_DIR"

cecho "BLUE" "Submitting lossy collective-communication experiments"

# recipe                 outputs    topology            netload   error workload      cc    pfc irn armode timeout window            rtoH rtoL buffer bw  group pattern        LBs
run_experiment_group "f13_a2a_base"         "figure13" "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      dcqcn 0   1   noar   0       "$AI_LEAF_WINDOW" 320  100  0.32   400 8     none           fecmp conweave
run_experiment_group "f13_a2a_packet"       "figure13" "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      dcqcn 0   1   ar     2       "$AI_LEAF_WINDOW" 320  100  0.32   400 8     none           drill rps adaptive
run_experiment_group "f13_allreduce_base"   "figure13" "$AI_LEAF_TOPOLOGY" 11234742  "0.0" RingAllreduce dcqcn 0   1   noar   0       "$AI_RING_WINDOW" 320  100  0.32   400 8     none           fecmp conweave
run_experiment_group "f13_allreduce_packet" "figure13" "$AI_LEAF_TOPOLOGY" 11234742  "0.0" RingAllreduce dcqcn 0   1   ar     2       "$AI_RING_WINDOW" 320  100  0.32   400 8     none           drill rps adaptive

run_experiment_group "f13_a2av_base"        "figure13" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   noar   0       "$AI_LEAF_WINDOW" 320  100  0.32   400 8     zipfian_incast fecmp conweave
run_experiment_group "f13_a2av_packet"      "figure13" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     2       "$AI_LEAF_WINDOW" 320  100  0.32   400 8     zipfian_incast drill rps adaptive
run_experiment_group "f13_a2av_base"        "figure13" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   noar   0       "$AI_LEAF_WINDOW" 320  100  0.32   400 16    zipfian_incast fecmp conweave
run_experiment_group "f13_a2av_packet"      "figure13" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     2       "$AI_LEAF_WINDOW" 320  100  0.32   400 16    zipfian_incast drill rps adaptive
run_experiment_group "f13_a2av_base"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   noar   0       "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast fecmp conweave
run_experiment_group "f13_a2av_packet"      "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     2       "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast drill rps adaptive
run_experiment_group "f13_a2av_base"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   noar   0       "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast fecmp conweave
run_experiment_group "f13_a2av_packet"      "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     2       "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast drill rps adaptive
run_experiment_group "f13_a2av_base"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   noar   0       "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast fecmp conweave
run_experiment_group "f13_a2av_packet"      "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     2       "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast drill rps adaptive

run_experiment_group "f13_a2av_trim"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   2   ar     0       "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast adaptive
run_experiment_group "f13_a2av_trim"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   2   ar     0       "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast adaptive
run_experiment_group "f13_a2av_trim"        "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   2   ar     0       "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast adaptive

run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     8       "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     32      "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     128     "$AI_FAT_WINDOW" 320  100  0.32   400 32    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     8       "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     32      "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     128     "$AI_FAT_WINDOW" 320  100  0.32   400 64    zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     8       "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     32      "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast adaptive
run_experiment_group "f13_a2av_reduction"   "figure13" "$AI_FAT_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn 0   1   ar     128     "$AI_FAT_WINDOW" 320  100  0.32   400 128   zipfian_incast adaptive

cecho "GREEN" "All experiment groups submitted; waiting for background jobs..."
task_failures=0
artifact_wait_for_tasks || task_failures=$?
if ((task_failures > 0)); then
    cecho "RED" "${task_failures} collective experiment(s) failed"
    artifact_tracking_finalize || true
    exit 1
fi
if artifact_tracking_enabled && ! artifact_tracking_finalize; then
    cecho "RED" "Collective run status is incomplete"
    exit 1
fi
cecho "BLUE" "Completed. Next: ${SCRIPT_DIR}/parse_results.sh"
