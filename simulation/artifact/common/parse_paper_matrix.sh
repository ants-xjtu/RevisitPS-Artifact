#!/usr/bin/env bash
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${COMMON_DIR}/.." && pwd)"
NS3_ROOT="$(cd "${ARTIFACT_DIR}/.." && pwd)"
PARSER_DIR="${NS3_ROOT}/parser"
RESULTS="${ARTIFACT_DIR}/results/extended"
FIGURES=()
REFERENCE_MANIFEST=""
REFERENCE_HISTORY=""

usage() {
    cat <<'EOF'
Usage: parse_paper_matrix.sh [options]

Options:
  --results-dir PATH  Read manifests and write parsed data below PATH
  --reference-manifest PATH  Manifest for cross-workload reference panels
  --reference-history PATH   History for cross-workload reference panels
  --figure NAME       Process one paper output; repeat for multiple outputs
  -h, --help          Show this help

With no --figure option, all Figure 7--17 and Table 5 data is processed.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --results-dir)
            (($# >= 2)) || die "--results-dir requires a value"
            RESULTS="$2"
            shift 2
            ;;
        --figure)
            (($# >= 2)) || die "--figure requires a value"
            FIGURES+=("$2")
            shift 2
            ;;
        --reference-manifest)
            (($# >= 2)) || die "--reference-manifest requires a value"
            REFERENCE_MANIFEST="$2"
            shift 2
            ;;
        --reference-history)
            (($# >= 2)) || die "--reference-history requires a value"
            REFERENCE_HISTORY="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

want() {
    local requested="$1"
    local item
    (("${#FIGURES[@]}" == 0)) && return 0
    for item in "${FIGURES[@]}"; do
        [[ "$item" == "$requested" ]] && return 0
    done
    return 1
}

MANIFEST="${RESULTS}/extended_runs.csv"
HISTORY="${RESULTS}/extended.history"
SELECTED="${RESULTS}/selected_history"
DATA="${RESULTS}/data"
STAGE="${RESULTS}/parser_stage"

[[ -s "$MANIFEST" ]] || die "missing ${MANIFEST}; run this group's experiments first"
[[ -s "$HISTORY" ]] || die "missing ${HISTORY}; run this group's experiments first"
mkdir -p "$SELECTED" "$DATA" "$STAGE"

select_history() {
    local output="$1"
    shift
    python3 "${COMMON_DIR}/select_history.py" "$MANIFEST" "$HISTORY" "$output" "$@"
}

select_history_from() {
    local manifest="$1" history="$2" output="$3"
    shift 3
    python3 "${COMMON_DIR}/select_history.py" "$manifest" "$history" "$output" "$@"
}

# Mirror an unchanged parser so its hard-coded output paths stay artifact-local.
stage_parser() {
    local name="$1"
    local parser_name="$2"
    shift 2
    local root="${STAGE}/${name}"
    mkdir -p "${root}/parser"
    cp "${PARSER_DIR}/${parser_name}" "${root}/parser/${parser_name}"
    ln -sfn "${NS3_ROOT}/mix" "${root}/mix"
    ln -sfn "${NS3_ROOT}/config" "${root}/config"
    ln -sfn "${NS3_ROOT}/analysis" "${root}/analysis"
    ln -sfn "${NS3_ROOT}/run.py" "${root}/run.py"
    PYTHONPATH="${root}:${NS3_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
        python3 "${root}/parser/${parser_name}" "$@"
}

if want figure7; then
    select_history "${SELECTED}/figure7.history" --figure figure7
    stage_parser figure7 parse_jct_with_ideal.py "${SELECTED}/figure7.history" --mode vs_groupsize --merge-timeout --merge-cc --group_size 8 --topology leaf_spine_L8_S16_400G_OS1 --bandwidth 400
fi

# Figure 8 contains both DCN references and collective workloads.
if want figure8; then
    pfc_items=(
        hadoop:FbHdp2015:1
        rpc:Solar2022:1
        storage:AliStorage2019:1
        a2av8:AlltoallV:8
        a2av32:AlltoallV:32
        a2av128:AlltoallV:128
    )
    for item in "${pfc_items[@]}"; do
        IFS=: read -r label workload group_size <<<"$item"
        selected="${SELECTED}/figure8_${label}.history"
        source_manifest="$MANIFEST"
        source_history="$HISTORY"
        if [[ "$workload" != "AlltoallV" ]]; then
            [[ -s "$REFERENCE_MANIFEST" ]] || die "missing Figure 8 datacenter manifest: $REFERENCE_MANIFEST"
            [[ -s "$REFERENCE_HISTORY" ]] || die "missing Figure 8 datacenter history: $REFERENCE_HISTORY"
            source_manifest="$REFERENCE_MANIFEST"
            source_history="$REFERENCE_HISTORY"
        fi
        select_history_from "$source_manifest" "$source_history" "$selected" \
            --figure figure8 --workload "$workload" --group-size "$group_size"
        stage_parser "figure8_${label}" parse_dcn_pfc_incast.py "$selected"
    done
fi

if want figure9; then
    selected="${SELECTED}/figure9_leafspine_storage.history"
    select_history "$selected" \
        --figure figure9 --topology leaf_spine_L8_S16_100G_OS1 \
        --workload AliStorage2019 --group-size 1
    stage_parser figure9_leafspine_storage parse_dcn_pfc_incast.py "$selected"
fi

if want figure10; then
    select_history "${SELECTED}/figure10.history" --figure figure10 --algorithm AR
    stage_parser figure10 parse_single_spine_qlen.py "${SELECTED}/figure10.history" --n_leaf 8 --n_spine 16 --servers_per_leaf 16
fi

if want table5; then
    select_history "${SELECTED}/table5.history" \
        --figure table5 --topology leaf_spine_L8_S16_100G_OS1 \
        --workload AliStorage2019 --group-size 1
    stage_parser table5 parse_dcn_pfc_spine_balance.py "${SELECTED}/table5.history" --servers-per-leaf 16
    python3 "${COMMON_DIR}/build_table5.py" "${STAGE}/table5/parser/json-data-pfc-spine-balance" "${RESULTS}/tables"
fi

for figure in figure11 figure12 figure14; do
    if want "$figure"; then
        select_history "${SELECTED}/${figure}.history" --figure "$figure"
        mkdir -p "${DATA}/${figure}"
        python3 "${PARSER_DIR}/parse_dcn_fct_rto.py" "${SELECTED}/${figure}.history" -o "${DATA}/${figure}"
    fi
done

if want figure13; then
    select_history "${SELECTED}/figure13.history" --figure figure13
    stage_parser figure13 parse_jct_with_ideal.py "${SELECTED}/figure13.history" --mode vs_groupsize --merge-timeout --merge-cc --group_size 8 --topology leaf_spine_L8_S16_400G_OS1 --bandwidth 400
fi

if want figure15; then
    select_history "${SELECTED}/figure15.history" --figure figure15
    stage_parser figure15_ooo parse_dcn_ooo.py "${SELECTED}/figure15.history"
    mkdir -p "${DATA}/figure15"
    cp "${SELECTED}/figure15.history" "${DATA}/figure15/figure15.history"
    stage_parser figure15_retrans parse_unnecc_retrans.py "${DATA}/figure15/figure15.history"
fi

if want figure16; then
    select_history "${SELECTED}/figure16.history" --figure figure16 --topology leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1
    mkdir -p "${DATA}/figure16"
    python3 "${PARSER_DIR}/parse_dcn_fct_rto.py" "${SELECTED}/figure16.history" -o "${DATA}/figure16"
fi

if want figure17; then
    select_history "${SELECTED}/figure17.history" --figure figure17
    stage_parser figure17 parse_jct_with_ideal.py "${SELECTED}/figure17.history" --mode per_group --merge-timeout --merge-cc --group_size 8 --topology leaf_spine_L8_S16_100G_OS1 --bandwidth 100
fi

echo "Parsed artifact data written below ${RESULTS}"
