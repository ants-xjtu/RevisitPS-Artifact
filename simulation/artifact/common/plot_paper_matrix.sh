#!/usr/bin/env bash
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${COMMON_DIR}/.." && pwd)"
NS3_ROOT="$(cd "${ARTIFACT_DIR}/.." && pwd)"
MONOREPO="$(cd "${NS3_ROOT}/.." && pwd)/plot"
RESULTS="${ARTIFACT_DIR}/results/extended"
DRY_RUN=0
SPINE_ID=136
FIGURES=()

usage() {
    cat <<'EOF'
Usage: plot_paper_matrix.sh [options]

Options:
  --results-dir PATH  Read parsed data and write figures below PATH
  --figure NAME       Plot one paper output; repeat for multiple outputs
  --spine-id ID       Spine node used for Figure 10 (default: 136)
  --dry-run           Print Bazel commands without running them
  -h, --help          Show this help
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
        --spine-id)
            (($# >= 2)) || die "--spine-id requires a value"
            SPINE_ID="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
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

[[ "$SPINE_ID" =~ ^[0-9]+$ ]] || die "invalid spine ID"
[[ -f "${MONOREPO}/main/plot_sample/BUILD.bazel" ]] || die "missing sibling plot workspace at ${MONOREPO}"

DATA="${RESULTS}/data"
STAGE="${RESULTS}/parser_stage"
FIGURE_DIR="${RESULTS}/figures"

run_plot() {
    local target="$1"
    shift
    if ((DRY_RUN)); then
        printf 'BAZEL_COMMAND bazel run %q --' "$target"
        printf ' %q' "$@"
        printf '\n'
    else
        (cd "$MONOREPO" && bazel run "$target" -- "$@")
    fi
}

((DRY_RUN)) || mkdir -p "$FIGURE_DIR"

if want figure7; then
    run_plot //main/plot_sample:plot_sim_ai_jct_avg "${STAGE}/figure7/parser/json-data-jct-vs-groupsize/test-trim" -o "${FIGURE_DIR}/figure7/a" --normalize --combined-group lossless-low-incast --raw-ytop 4 --all-combos
    run_plot //main/plot_sample:plot_sim_ai_jct_avg "${STAGE}/figure7/parser/json-data-jct-vs-groupsize/test-trim" -o "${FIGURE_DIR}/figure7/b" --normalize --combined-group lossless-high-incast --raw-ytop 4 --all-combos
fi

pfc_json() {
    local label="$1"
    local load="$2"
    local workload="$3"
    local topology=leaf_spine_L8_S16_100G_OS1
    case "$label" in
        a2av*) topology=leaf_spine_L8_S16_400G_OS1 ;;
    esac
    printf '%s/figure8_%s/parser/json-data-pfc-incast-workload/PFC_INCAST_DATA_TOPO_%s_LOAD_%s_FC_Lossless_TYPE_%s_ERR_0.0.json' "$STAGE" "$label" "$topology" "$load" "$workload"
}

if want figure8; then
    figure8_inputs=(
        "$(pfc_json hadoop 80 FbHdp2015)"
        "$(pfc_json rpc 80 Solar2022)"
        "$(pfc_json storage 80 AliStorage2019)"
        "$(pfc_json a2av8 157286400 AlltoallV)"
        "$(pfc_json a2av32 157286400 AlltoallV)"
        "$(pfc_json a2av128 157286400 AlltoallV)"
    )
    run_plot //main/plot_sample:plot_dcn_pfc_incast "${figure8_inputs[@]}" --output-prefix "${FIGURE_DIR}/figure8" --lb-mode AR
fi

if want figure9; then
    figure9_json="${STAGE}/figure9_leafspine_storage/parser/json-data-pfc-incast-workload/PFC_INCAST_DATA_TOPO_leaf_spine_L8_S16_100G_OS1_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"
    run_plot //main/plot_sample:plot_dcn_pfc_incast "$figure9_json" --output-prefix "${FIGURE_DIR}/figure9" --queue-x-max 4
fi

if want figure10; then
    figure10_json="${STAGE}/figure10/parser/json-data-spine-qlen-by-port/QLEN_DATA_TOPO_leaf_spine_L8_S16_400G_OS1_LOAD_22469485_FC_Lossless_TYPE_Alltoall_ERR_0.0.json"
    run_plot //main/plot_sample:plot_single_spine_qlen "$figure10_json" --spine_id "$SPINE_ID" --top_n 4 --y_step 200 --smooth 5
fi

for figure in figure11 figure12 figure14; do
    if want "$figure"; then
        run_plot //main/plot_sample:plot_dcn_rto_fct "${DATA}/${figure}"
    fi
done

if want figure13; then
    run_plot //main/plot_sample:plot_sim_ai_jct_avg "${STAGE}/figure13/parser/json-data-jct-vs-groupsize/test-trim" -o "${FIGURE_DIR}/figure13" --normalize --combined --all-combos
fi

if want figure15; then
    figure15_ooo="${STAGE}/figure15_ooo/parser/json-data-ooo-asy/OOO_DATA_TOPO_leafspine_L8_S16_100G_AsymBw10pct_R0.5_OS1_LOAD_80_FC_Lossy_TYPE_FbHdp2015_ERR_0.0.json"
    run_plot //main/plot_sample:plot_dcn_ooo "$figure15_ooo"
    run_plot //main/plot_sample:plot_dcn_unnecessary_retrans "${DATA}/figure15/figure15_retrans_trace.csv"
fi

if want figure16; then
    run_plot //main/plot_sample:plot_dcn_rto_fct_trim_vs_rto "${DATA}/figure16"
fi

if want figure17; then
    run_plot //main/plot_sample:plot_sim_ai_jct_avg_asy "${STAGE}/figure17/parser/json-data-jct-with-ideal" -o "${FIGURE_DIR}/figure17" --normalize --by-scenario --hide-recovery --no-conga --all-combos
fi

echo "Selected figures written below ${RESULTS}"
