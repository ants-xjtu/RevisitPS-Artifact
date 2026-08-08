#!/usr/bin/env bash
set -euo pipefail

# Artifact orchestration. Parser and plot implementations live in new
# artifact-specific directories and do not modify the legacy parser/plot code.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${NS3_ROOT}/.." && pwd)"
MONOREPO="${REPO_ROOT}/plot"
SECTION="all"
STAGE="all"
RUN_ID="latest"
DRY_RUN=0
SPINE_ID=136

usage() {
    cat <<'EOF'
Usage: ./artifact/run_artifact.sh [options]

Options:
  --section lossless|lossy|asymmetric|all
  --stage run|parse|plot|all
  --run-id ID             Result run directory name (default: latest)
  --dry-run               Print commands without running them
  --spine-id ID           Figure 10 spine node (default: 136)
  -h, --help

Managed results:
  artifact/results/<section>/<workload-family>/runs/<run-id>/
    history/all.history
    history/<semantic-output>.history
    manifest.csv
    json/<semantic-output>/
    figures/
    tables/
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --section) (($# >= 2)) || die "--section requires a value"; SECTION="$2"; shift 2 ;;
        --stage) (($# >= 2)) || die "--stage requires a value"; STAGE="$2"; shift 2 ;;
        --run-id) (($# >= 2)) || die "--run-id requires a value"; RUN_ID="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --spine-id) (($# >= 2)) || die "--spine-id requires a value"; SPINE_ID="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ "$SECTION" =~ ^(lossless|lossy|asymmetric|all)$ ]] || die "invalid --section: $SECTION"
[[ "$STAGE" =~ ^(run|parse|plot|all)$ ]] || die "invalid --stage: $STAGE"

DRY_ARGS=()
if ((DRY_RUN)); then DRY_ARGS=(--dry-run); fi

run_cmd() {
    if ((DRY_RUN)); then
        printf 'RUN_COMMAND'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

want_section() {
    [[ "$SECTION" == "all" || "$SECTION" == "$1" ]]
}

run_dir() {
    printf '%s/results/%s/%s/runs/%s' "$SCRIPT_DIR" "$1" "$2" "$RUN_ID"
}

prepare_run_dir() {
    local section="$1" workload="$2" dir
    dir="$(run_dir "$section" "$workload")"
    mkdir -p "$dir/history" "$dir/json" "$dir/figures" "$dir/tables" "$dir/parser_stage"
}

import_history_one() {
    local section="$1" workload="$2" history_src="$3" manifest_src="${4:-}" dir
    dir="$(run_dir "$section" "$workload")"
    prepare_run_dir "$section" "$workload"
    if [[ -s "$history_src" ]]; then
        cp "$history_src" "$dir/history/all.history"
    fi
    if [[ -n "$manifest_src" && -s "$manifest_src" ]]; then
        cp "$manifest_src" "$dir/manifest.csv"
    fi
}

import_history_lossless() {
    import_history_one lossless datacenter-workloads \
        "$SCRIPT_DIR/lossless/datacenter-workloads/results/lossless_datacenter.history"
    import_history_one lossless collective-communication-workloads \
        "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended.history" \
        "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended_runs.csv"
}

import_history_lossy() {
    import_history_one lossy datacenter-workloads \
        "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended.history" \
        "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended_runs.csv"
    import_history_one lossy collective-communication-workloads \
        "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended.history" \
        "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended_runs.csv"
}

import_history_asymmetric() {
    import_history_one asymmetric datacenter-workloads \
        "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended.history" \
        "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended_runs.csv"
    import_history_one asymmetric collective-communication-workloads \
        "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended.history" \
        "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended_runs.csv"
}

run_stage() {
    if want_section lossless; then
        run_cmd "$SCRIPT_DIR/lossless/datacenter-workloads/run_experiments.sh"
        run_cmd "$SCRIPT_DIR/lossless/collective-communication-workloads/run_experiments.sh"
        ((DRY_RUN)) || import_history_lossless
    fi
    if want_section lossy; then
        run_cmd "$SCRIPT_DIR/lossy/datacenter-workloads/run_experiments.sh"
        run_cmd "$SCRIPT_DIR/lossy/collective-communication-workloads/run_experiments.sh"
        ((DRY_RUN)) || import_history_lossy
    fi
    if want_section asymmetric; then
        run_cmd "$SCRIPT_DIR/asymmetric/datacenter-workloads/run_experiments.sh"
        run_cmd "$SCRIPT_DIR/asymmetric/collective-communication-workloads/run_experiments.sh"
        ((DRY_RUN)) || import_history_asymmetric
    fi
}

require_history() {
    local section="$1" workload="$2" need_manifest="${3:-0}" dir
    dir="$(run_dir "$section" "$workload")"
    [[ -s "$dir/history/all.history" ]] || die "missing $dir/history/all.history; run this group first"
    if [[ "$need_manifest" == "1" ]]; then
        [[ -s "$dir/manifest.csv" ]] || die "missing $dir/manifest.csv; run this group first"
    fi
}

parser_dir() { printf '%s/parser/artifact/%s' "$NS3_ROOT" "$1"; }
plot_dir() { printf '%s/main/plot_artifact/%s' "$MONOREPO" "$1"; }

parse_one() {
    local section="$1" workload="$2" script="$3" output="$4" dir parser_root
    shift 4
    dir="$(run_dir "$section" "$workload")"
    parser_root="$(parser_dir "$section")"
    run_cmd python3 "$parser_root/$script" \
        --history "$dir/history/all.history" \
        --selected-history "$dir/history/$output.history" \
        --output-dir "$dir/json/$output" \
        --stage-dir "$dir/parser_stage/$output" \
        --ns3-root "$NS3_ROOT" \
        "${DRY_ARGS[@]}" \
        "$@"
}

parse_stage() {
    if ! ((DRY_RUN)); then
        want_section lossless && import_history_lossless
        want_section lossy && import_history_lossy
        want_section asymmetric && import_history_asymmetric
    fi
    if want_section lossless; then
        if ! ((DRY_RUN)); then
            require_history lossless datacenter-workloads 0
            require_history lossless collective-communication-workloads 1
        fi
        parse_one lossless datacenter-workloads parse_fig04_lossless_dcn_p99_fct.py fig04_lossless_dcn_p99_fct
        parse_one lossless datacenter-workloads parse_fig05_lossless_ooo_degree.py fig05_lossless_ooo_degree
        parse_one lossless datacenter-workloads parse_fig06_lossless_pfc_pause_duration.py fig06_lossless_pfc_pause_duration
        parse_one lossless datacenter-workloads parse_tbl04_lossless_avg_egress_queue.py tbl04_lossless_avg_egress_queue --table-dir "$(run_dir lossless datacenter-workloads)/tables"
        parse_one lossless collective-communication-workloads parse_fig07_lossless_ai_collective_cct.py fig07_lossless_ai_collective_cct --manifest "$(run_dir lossless collective-communication-workloads)/manifest.csv"
        parse_one lossless collective-communication-workloads parse_fig08_lossless_pfc_incast_degree.py fig08_lossless_pfc_incast_degree --manifest "$(run_dir lossless collective-communication-workloads)/manifest.csv"
        parse_one lossless collective-communication-workloads parse_fig09_lossless_queue_per_pfc_event.py fig09_lossless_queue_per_pfc_event --manifest "$(run_dir lossless collective-communication-workloads)/manifest.csv"
        parse_one lossless collective-communication-workloads parse_fig10_lossless_spine_queue_timeseries.py fig10_lossless_spine_queue_timeseries --manifest "$(run_dir lossless collective-communication-workloads)/manifest.csv"
        parse_one lossless collective-communication-workloads parse_tbl05_lossless_spine_pause_balance.py tbl05_lossless_spine_pause_balance --manifest "$(run_dir lossless collective-communication-workloads)/manifest.csv" --table-dir "$(run_dir lossless collective-communication-workloads)/tables"
    fi
    if want_section lossy; then
        if ! ((DRY_RUN)); then
            require_history lossy datacenter-workloads 1
            require_history lossy collective-communication-workloads 1
        fi
        parse_one lossy datacenter-workloads parse_fig11_lossy_dcn_p99_fct_leafspine.py fig11_lossy_dcn_p99_fct_leafspine --manifest "$(run_dir lossy datacenter-workloads)/manifest.csv"
        parse_one lossy datacenter-workloads parse_fig12_lossy_dcn_p99_fct_fattree.py fig12_lossy_dcn_p99_fct_fattree --manifest "$(run_dir lossy datacenter-workloads)/manifest.csv"
        parse_one lossy collective-communication-workloads parse_fig13_lossy_ai_collective_cct.py fig13_lossy_ai_collective_cct --manifest "$(run_dir lossy collective-communication-workloads)/manifest.csv"
    fi
    if want_section asymmetric; then
        if ! ((DRY_RUN)); then
            require_history asymmetric datacenter-workloads 1
            require_history asymmetric collective-communication-workloads 1
        fi
        parse_one asymmetric datacenter-workloads parse_fig14_asym_dcn_fct.py fig14_asym_dcn_fct --manifest "$(run_dir asymmetric datacenter-workloads)/manifest.csv"
        parse_one asymmetric datacenter-workloads parse_fig15_asym_ooo_retransmission.py fig15_asym_ooo_retransmission --manifest "$(run_dir asymmetric datacenter-workloads)/manifest.csv"
        parse_one asymmetric datacenter-workloads parse_fig16_asym_packet_trim_rto.py fig16_asym_packet_trim_rto --manifest "$(run_dir asymmetric datacenter-workloads)/manifest.csv"
        parse_one asymmetric collective-communication-workloads parse_fig17_asym_ai_collective_cct.py fig17_asym_ai_collective_cct --manifest "$(run_dir asymmetric collective-communication-workloads)/manifest.csv"
    fi
}

plot_one() {
    local section="$1" workload="$2" script="$3" output="$4" dir plot_root
    shift 4
    dir="$(run_dir "$section" "$workload")"
    plot_root="$(plot_dir "$section")"
    run_cmd python3 "$plot_root/$script" \
        --input-dir "$dir/json/$output" \
        --output-dir "$dir/figures" \
        "${DRY_ARGS[@]}" \
        "$@"
}

plot_stage() {
    if want_section lossless; then
        plot_one lossless datacenter-workloads plot_fig04_lossless_dcn_p99_fct.py fig04_lossless_dcn_p99_fct
        plot_one lossless datacenter-workloads plot_fig05_lossless_ooo_degree.py fig05_lossless_ooo_degree
        plot_one lossless datacenter-workloads plot_fig06_lossless_pfc_pause_duration.py fig06_lossless_pfc_pause_duration
        plot_one lossless collective-communication-workloads plot_fig07_lossless_ai_collective_cct.py fig07_lossless_ai_collective_cct
        plot_one lossless collective-communication-workloads plot_fig08_lossless_pfc_incast_degree.py fig08_lossless_pfc_incast_degree
        plot_one lossless collective-communication-workloads plot_fig09_lossless_queue_per_pfc_event.py fig09_lossless_queue_per_pfc_event
        plot_one lossless collective-communication-workloads plot_fig10_lossless_spine_queue_timeseries.py fig10_lossless_spine_queue_timeseries --spine-id "$SPINE_ID"
    fi
    if want_section lossy; then
        plot_one lossy datacenter-workloads plot_fig11_lossy_dcn_p99_fct_leafspine.py fig11_lossy_dcn_p99_fct_leafspine
        plot_one lossy datacenter-workloads plot_fig12_lossy_dcn_p99_fct_fattree.py fig12_lossy_dcn_p99_fct_fattree
        plot_one lossy collective-communication-workloads plot_fig13_lossy_ai_collective_cct.py fig13_lossy_ai_collective_cct
    fi
    if want_section asymmetric; then
        plot_one asymmetric datacenter-workloads plot_fig14_asym_dcn_fct.py fig14_asym_dcn_fct
        plot_one asymmetric datacenter-workloads plot_fig15_asym_ooo_retransmission.py fig15_asym_ooo_retransmission
        plot_one asymmetric datacenter-workloads plot_fig16_asym_packet_trim_rto.py fig16_asym_packet_trim_rto
        plot_one asymmetric collective-communication-workloads plot_fig17_asym_ai_collective_cct.py fig17_asym_ai_collective_cct
    fi
}

case "$STAGE" in
    run) run_stage ;;
    parse) parse_stage ;;
    plot) plot_stage ;;
    all) run_stage; parse_stage; plot_stage ;;
esac
