#!/bin/bash

# ==============================================================================
# Asymmetric datacenter workloads: Figures 14--16
# Reference: autorun_asy.sh
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
    RESULTS_DIR="${ARTIFACT_DIR}/results/asymmetric/datacenter-workloads"
    LOG_DIR="${RESULTS_DIR}/logs"
    HISTORY_FILE="${RESULTS_DIR}/extended.history"
    MANIFEST_FILE="${RESULTS_DIR}/extended_runs.csv"
fi

MAX_JOBS=60
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"
RUNTIME="0.05"
FLOWGEN="src"

cecho() {
    RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
    BLUE="\033[0;34m"; NC="\033[0m"
    printf "${!1}${2}${NC}\n"
}

lb_label() {
    case "$1" in
        fecmp) echo "ECMP" ;;
        conweave) echo "ConWeave" ;;
        rps) echo "RPS" ;;
        adaptive) echo "AR" ;;
        drill) echo "DRILL" ;;
        drillgroup) echo "DRILLGroup" ;;
        sglb) echo "SGLB" ;;
        *) echo "$1" ;;
    esac
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
#   1 recipe, 2 paper outputs, 3 topology, 4 load, 5 error rate,
#   6 workload, 7 CC, 8 PFC, 9 IRN, 10 armode, 11 timeout,
#   12 window, 13 RTO high, 14 RTO low, 15 buffer, 16 bandwidth,
#   17... load-balancing algorithms.
run_experiment_group() {
    local recipe=$1 paper_outputs=$2 topology=$3 netload=$4 error_rate=$5 cdf=$6
    local cc=$7 pfc=$8 irn=$9 armode=${10} timeout_mode=${11}
    local win_size=${12} rto_high=${13} rto_low=${14}
    local buffer_size=${15} bandwidth=${16}
    shift 16
    local lbs=("$@")

    cecho "GREEN" "Submit: RECIPE=${recipe} TOPO=${topology} CDF=${cdf} CC=${cc} PFC=${pfc} IRN=${irn} TIMEOUT=${timeout_mode} LBs=${lbs[*]}"
    for lb in "${lbs[@]}"; do
        local algorithm
        algorithm=$(lb_label "$lb")
        local task_id="${recipe}__${topology}__${cdf}__g1__${algorithm}__t${timeout_mode}"
        local log_file="${LOG_DIR}/${task_id}.log"
        run_if_slot_free "$task_id" "$log_file" \
            artifact_run_command "$MANIFEST_FILE" "$task_id" "$recipe" \
            "$paper_outputs" "$topology" "$cdf" 1 "$algorithm" \
            "$timeout_mode" python3 run.py \
            --cc "$cc" --lb "$lb" --pfc "$pfc" --irn "$irn" --armode "$armode" \
            --simul_time "$RUNTIME" --netload "$netload" --topo "$topology" \
            --cdf "$cdf" --error_rate "$error_rate" --flowgen_mode "$FLOWGEN" \
            --timeout_slowstart_mode "$timeout_mode" --windowSize "$win_size" \
            --rto_high "$rto_high" --rto_low "$rto_low" \
            --buffer "$buffer_size" --bw "$bandwidth"
    done
}

cd "$NS3_ROOT" || exit 1
artifact_prepare_simulator "$NS3_ROOT" || exit 1
artifact_tracking_init asymmetric datacenter-workloads 26 || exit 1
artifact_result_files_init "$HISTORY_FILE" "$MANIFEST_FILE" || exit 1
mkdir -p "$LOG_DIR"

cecho "BLUE" "Submitting asymmetric datacenter experiments"

# recipe             outputs                      topology                                     load error workload  cc    pfc irn armode timeout window rtoH rtoL buffer bw  LBs
run_experiment_group "f14_baseline"     "figure14"                   "leafspine_L8_S16_100G_AsymFail1pct_OS1"     80   "0.0" FbHdp2015 dcqcn 0   1   noar   0       104000 320  320  0      100 fecmp conweave
run_experiment_group "f14_packet_other" "figure14;figure15"          "leafspine_L8_S16_100G_AsymFail1pct_OS1"     80   "0.0" FbHdp2015 dcqcn 0   1   ar     2       104000 320  320  0      100 rps adaptive drill sglb
run_experiment_group "f14_baseline"     "figure14"                   "leafspine_L8_S16_100G_AsymFail10pct_OS1"    80   "0.0" FbHdp2015 dcqcn 0   1   noar   0       104000 320  320  0      100 fecmp conweave
run_experiment_group "f14_packet_other" "figure14;figure15"          "leafspine_L8_S16_100G_AsymFail10pct_OS1"    80   "0.0" FbHdp2015 dcqcn 0   1   ar     2       104000 320  320  0      100 rps adaptive drill sglb
run_experiment_group "f14_baseline"     "figure14"                   "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1" 80   "0.0" FbHdp2015 dcqcn 0   1   noar   0       104000 320  320  0      100 fecmp conweave
run_experiment_group "f14_packet_other" "figure14;figure15"          "leafspine_L8_S16_100G_AsymBw20pct_R0.5_OS1" 80   "0.0" FbHdp2015 dcqcn 0   1   ar     2       104000 320  320  0      100 rps adaptive drillgroup sglb
run_experiment_group "f14_baseline"     "figure14"                   "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1" 80   "0.0" FbHdp2015 dcqcn 0   1   noar   0       104000 320  320  0      100 fecmp conweave
run_experiment_group "f14_packet_s3"    "figure14;figure15;figure16;table8" "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1" 80   "0.0" FbHdp2015 dcqcn 0   1   ar     2       104000 320  320  0      100 rps adaptive drillgroup sglb
run_experiment_group "f16_trim"         "figure16"                   "leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1" 80   "0.0" FbHdp2015 dcqcn 0   2   ar     2       104000 320  320  0      100 rps adaptive

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
cecho "BLUE" "Completed. Next: ${SCRIPT_DIR}/parse_results.sh"
