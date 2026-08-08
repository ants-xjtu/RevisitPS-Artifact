#!/bin/bash

# ==============================================================================
# Lossless collective-communication workloads: Figures 7--10 and Table 5
# Reference: autorun_ai.sh
#
# Every experiment is listed explicitly at the bottom. Parameter order is
# documented above run_experiment_group().
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NS3_ROOT="$(cd "${ARTIFACT_DIR}/.." && pwd)"
RESULTS_DIR="${ARTIFACT_DIR}/results/lossless/collective-communication-workloads"
LOG_DIR="${RESULTS_DIR}/logs"
HISTORY_FILE="${RESULTS_DIR}/extended.history"
MANIFEST_FILE="${RESULTS_DIR}/extended_runs.csv"

MAX_JOBS=45
PROCESS_PATTERN_TO_MONITOR="build/scratch/network-load-balance"
RUNTIME="0.05"
FLOWGEN="src"
AI_LEAF_TOPOLOGY="leaf_spine_L8_S16_400G_OS1"
AI_LEAF_WINDOW=404000
AI_RING_WINDOW=1024000

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
        drillgroup) echo "DRILLGroup" ;;
        sglb) echo "SGLB" ;;
        *) echo "$1" ;;
    esac
}

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
#   1 recipe, 2 paper outputs, 3 topology, 4 netload, 5 error rate,
#   6 workload, 7 CC, 8 PFC, 9 IRN, 10 armode, 11 timeout,
#   12 window, 13 RTO high, 14 RTO low, 15 buffer, 16 bandwidth,
#   17 AI nodes/group, 18 AlltoallV pattern (none for other workloads),
#   19... load-balancing algorithms.
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
    local bandwidth=${16}
    local ai_nodes_per_group=${17}
    local pattern=${18}
    shift 18
    local lbs=("$@")

    cecho "GREEN" "Submit: RECIPE=${recipe} TOPO=${topology} CDF=${cdf} N=${ai_nodes_per_group} CC=${cc} PFC=${pfc} IRN=${irn} TIMEOUT=${timeout_mode} LBs=${lbs[*]}"

    for lb in "${lbs[@]}"; do
        local algorithm
        algorithm=$(lb_label "$lb")
        local task_id="${recipe}__${topology}__${cdf}__g${ai_nodes_per_group}__${algorithm}__t${timeout_mode}"
        local log_file="${LOG_DIR}/${task_id}.log"

        RUN_LOGS+=("$log_file")
        RUN_RECIPES+=("$recipe")
        RUN_OUTPUTS+=("$paper_outputs")
        RUN_TOPOLOGIES+=("$topology")
        RUN_WORKLOADS+=("$cdf")
        RUN_GROUP_SIZES+=("$ai_nodes_per_group")
        RUN_ALGORITHMS+=("$algorithm")
        RUN_TIMEOUTS+=("$timeout_mode")

        local command=(
            python3 run.py
            --cc "$cc" --lb "$lb" --pfc "$pfc" --irn "$irn" --armode "$armode"
            --simul_time "$RUNTIME" --netload "$netload" --topo "$topology"
            --cdf "$cdf" --error_rate "$error_rate" --flowgen_mode "$FLOWGEN"
            --timeout_slowstart_mode "$timeout_mode" --windowSize "$win_size"
            --rto_high "$rto_high" --rto_low "$rto_low"
            --buffer "$buffer_size" --bw "$bandwidth"
        )
        if [[ "$cdf" == "Alltoall" || "$cdf" == "RingAllreduce" || "$cdf" == "AlltoallV" ]]; then
            command+=(--ai_nodes_per_group "$ai_nodes_per_group")
        fi
        if [[ "$cdf" == "AlltoallV" ]]; then
            command+=(--netload_pattern "$pattern")
        fi
        run_if_slot_free "$log_file" "${command[@]}"
    done
}

cd "$NS3_ROOT" || exit 1
mkdir -p "$LOG_DIR"
RUN_LOGS=()
RUN_RECIPES=()
RUN_OUTPUTS=()
RUN_TOPOLOGIES=()
RUN_WORKLOADS=()
RUN_GROUP_SIZES=()
RUN_ALGORITHMS=()
RUN_TIMEOUTS=()

cecho "BLUE" "Submitting lossless collective-communication experiments"

# recipe                 outputs                       topology                         netload   error workload       cc      pfc irn armode timeout window rtoH rtoL buffer bw  group pattern          LBs
run_experiment_group "f7_a2a_base"          "figure7"                     "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     none             fecmp conweave
run_experiment_group "f7_a2a_packet"        "figure7"                     "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     none             drill rps adaptive
run_experiment_group "f7_a2a_no_cc_other"   "figure7"                     "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      none    1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     none             drill rps
run_experiment_group "f7_a2a_no_cc_ar"      "figure7;figure10"            "$AI_LEAF_TOPOLOGY" 22469485  "0.0" Alltoall      none    1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     none             adaptive

run_experiment_group "f7_allreduce_base"    "figure7"                     "$AI_LEAF_TOPOLOGY" 11234742  "0.0" RingAllreduce dcqcn   1   0   noar   0       "$AI_RING_WINDOW" 4000 4000 0.32   400 8     none             fecmp conweave
run_experiment_group "f7_allreduce_packet"  "figure7"                     "$AI_LEAF_TOPOLOGY" 11234742  "0.0" RingAllreduce dcqcn   1   0   ar     0       "$AI_RING_WINDOW" 4000 4000 0.32   400 8     none             drill rps adaptive
run_experiment_group "f7_allreduce_no_cc"   "figure7"                     "$AI_LEAF_TOPOLOGY" 11234742  "0.0" RingAllreduce none    1   0   ar     0       "$AI_RING_WINDOW" 4000 4000 0.32   400 8     none             drill rps adaptive

run_experiment_group "f7_a2av_low_base"     "figure7;figure8"             "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     zipfian_incast  fecmp conweave
run_experiment_group "f7_a2av_low_packet"   "figure7;figure8"             "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     zipfian_incast  drill rps adaptive
run_experiment_group "f7_a2av_low_no_cc"    "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     none    1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 8     zipfian_incast  drill rps adaptive
run_experiment_group "f7_a2av_low_base"     "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 16    zipfian_incast  fecmp conweave
run_experiment_group "f7_a2av_low_packet"   "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 16    zipfian_incast  drill rps adaptive
run_experiment_group "f7_a2av_low_no_cc"    "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     none    1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 16    zipfian_incast  drill rps adaptive

run_experiment_group "f7_a2av_high_base"    "figure7;figure8"             "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 32    zipfian_incast  fecmp conweave
run_experiment_group "f7_a2av_high_packet"  "figure7;figure8"             "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 32    zipfian_incast  drill rps adaptive
run_experiment_group "f7_a2av_high_base"    "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 64    zipfian_incast  fecmp conweave
run_experiment_group "f7_a2av_high_packet"  "figure7"                     "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV     dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 64    zipfian_incast  drill rps adaptive

run_experiment_group "f7_a2av_128_base"     "figure7;figure8;figure9;table5" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV   dcqcn   1   0   noar   0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 128   zipfian_incast  fecmp conweave
run_experiment_group "f7_a2av_128_packet"   "figure7;figure8;figure9;table5" "$AI_LEAF_TOPOLOGY" 157286400 "0.0" AlltoallV   dcqcn   1   0   ar     0       "$AI_LEAF_WINDOW" 4000 4000 0.32   400 128   zipfian_incast  drill rps adaptive

# Figure 8 datacenter reference panels.
run_experiment_group "pfc_dcn_workloads"    "figure8"                     "leaf_spine_L8_S16_100G_OS1" 80        "0.0" FbHdp2015     dcqcn   1   0   ar     0       104000 4096 4096 0      100 1     none             adaptive
run_experiment_group "pfc_dcn_workloads"    "figure8"                     "leaf_spine_L8_S16_100G_OS1" 80        "0.0" Solar2022     dcqcn   1   0   ar     0       104000 4096 4096 0      100 1     none             adaptive
run_experiment_group "pfc_dcn_workloads"    "figure8"                     "leaf_spine_L8_S16_100G_OS1" 80        "0.0" AliStorage2019 dcqcn  1   0   ar     0       104000 4096 4096 0      100 1     none             adaptive

cecho "GREEN" "All experiment groups submitted; waiting for background jobs..."
wait

: > "$HISTORY_FILE"
printf '%s\n' "task_id,recipe,paper_outputs,config_id,topology,workload,group_size,algorithm,timeout_mode,command" > "$MANIFEST_FILE"
for index in "${!RUN_LOGS[@]}"; do
    log_file=${RUN_LOGS[$index]}
    config_id=$(sed -n 's#.*Config filename:.*/mix/output/\([^/]*\)/config.txt.*#\1#p' "$log_file" | tail -n 1)
    [ -n "$config_id" ] || { cecho "RED" "Cannot find config ID in ${log_file}"; exit 1; }
    history_row=$(awk -F, -v id="$config_id" '$2 == id {print; exit}' mix/.history)
    [ -n "$history_row" ] || { cecho "RED" "Cannot find history for ${config_id}"; exit 1; }
    printf '%s\n' "$history_row" >> "$HISTORY_FILE"
    task_id="${RUN_RECIPES[$index]}__${RUN_TOPOLOGIES[$index]}__${RUN_WORKLOADS[$index]}__g${RUN_GROUP_SIZES[$index]}__${RUN_ALGORITHMS[$index]}__t${RUN_TIMEOUTS[$index]}"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$task_id" "${RUN_RECIPES[$index]}" "${RUN_OUTPUTS[$index]}" "$config_id" "${RUN_TOPOLOGIES[$index]}" "${RUN_WORKLOADS[$index]}" "${RUN_GROUP_SIZES[$index]}" "${RUN_ALGORITHMS[$index]}" "${RUN_TIMEOUTS[$index]}" "python3 run.py" >> "$MANIFEST_FILE"
done

cecho "BLUE" "Completed. Next: ${SCRIPT_DIR}/parse_results.sh"
