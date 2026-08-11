#!/usr/bin/env bash
set -euo pipefail

# Artifact orchestration. Parser and plot implementations live in new
# artifact-specific directories and do not modify the legacy parser/plot code.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${NS3_ROOT}/.." && pwd)"
MONOREPO="${REPO_ROOT}/plot"
SECTION="all"
WORKLOAD="all"
STAGE="all"
RUN_ID="latest"
DRY_RUN=0
SPINE_ID=136

usage() {
    cat <<'EOF'
Usage: ./artifact/run_artifact.sh [options]

Options:
  --section lossless|lossy|asymmetric|all
  --workload datacenter-workloads|collective-communication-workloads|all
  --stage run|parse|plot|status|all
  --run-id ID             Result run directory name (default: latest)
  --dry-run               Print commands without running them
  --spine-id ID           Figure 10 spine node (default: 136)
  -h, --help

Managed results:
  artifact/results/<section>/<workload-family>/runs/<run-id>/
    status                 Overall state: running, completed, or failed
    status.json            Per-task progress and exit status
    history/all.history
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
        --workload) (($# >= 2)) || die "--workload requires a value"; WORKLOAD="$2"; shift 2 ;;
        --stage) (($# >= 2)) || die "--stage requires a value"; STAGE="$2"; shift 2 ;;
        --run-id) (($# >= 2)) || die "--run-id requires a value"; RUN_ID="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --spine-id) (($# >= 2)) || die "--spine-id requires a value"; SPINE_ID="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ "$SECTION" =~ ^(lossless|lossy|asymmetric|all)$ ]] || die "invalid --section: $SECTION"
[[ "$WORKLOAD" =~ ^(datacenter-workloads|collective-communication-workloads|all)$ ]] || die "invalid --workload: $WORKLOAD"
[[ "$STAGE" =~ ^(run|parse|plot|status|all)$ ]] || die "invalid --stage: $STAGE"
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "invalid --run-id: $RUN_ID"

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

want_workload() {
    [[ "$WORKLOAD" == "all" || "$WORKLOAD" == "$1" ]]
}

run_dir() {
    printf '%s/results/%s/%s/runs/%s' "$SCRIPT_DIR" "$1" "$2" "$RUN_ID"
}

prepare_run_dir() {
    local section="$1" workload="$2" dir
    dir="$(run_dir "$section" "$workload")"
    mkdir -p "$dir/history" "$dir/logs" "$dir/json" "$dir/figures" "$dir/tables"
}

import_history_one() {
    local section="$1" workload="$2" history_src="$3" manifest_src="${4:-}" dir
    dir="$(run_dir "$section" "$workload")"
    prepare_run_dir "$section" "$workload"
    if [[ ! -s "$dir/history/all.history" && -s "$history_src" ]]; then
        cp "$history_src" "$dir/history/all.history"
    fi
    if [[ ! -s "$dir/manifest.csv" && -n "$manifest_src" && -s "$manifest_src" ]]; then
        cp "$manifest_src" "$dir/manifest.csv"
    fi
}

run_workload() {
    local label="$1"
    shift
    if run_cmd "$@"; then
        return 0
    fi
    printf 'ERROR: %s failed; continuing with remaining workload groups.\n' "$label" >&2
    return 1
}

run_stage() {
    local failed=0
    if want_section lossless; then
        if want_workload datacenter-workloads; then
            run_workload lossless/datacenter-workloads env ARTIFACT_RUN_DIR="$(run_dir lossless datacenter-workloads)" \
                "$SCRIPT_DIR/lossless/datacenter-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one lossless datacenter-workloads \
                "$SCRIPT_DIR/lossless/datacenter-workloads/results/lossless_datacenter.history" \
                "$SCRIPT_DIR/lossless/datacenter-workloads/results/lossless_datacenter_runs.csv"
        fi
        if want_workload collective-communication-workloads; then
            run_workload lossless/collective-communication-workloads env ARTIFACT_RUN_DIR="$(run_dir lossless collective-communication-workloads)" \
                "$SCRIPT_DIR/lossless/collective-communication-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one lossless collective-communication-workloads \
                "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended_runs.csv"
        fi
    fi
    if want_section lossy; then
        if want_workload datacenter-workloads; then
            run_workload lossy/datacenter-workloads env ARTIFACT_RUN_DIR="$(run_dir lossy datacenter-workloads)" \
                "$SCRIPT_DIR/lossy/datacenter-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one lossy datacenter-workloads \
                "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended_runs.csv"
        fi
        if want_workload collective-communication-workloads; then
            run_workload lossy/collective-communication-workloads env ARTIFACT_RUN_DIR="$(run_dir lossy collective-communication-workloads)" \
                "$SCRIPT_DIR/lossy/collective-communication-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one lossy collective-communication-workloads \
                "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended_runs.csv"
        fi
    fi
    if want_section asymmetric; then
        if want_workload datacenter-workloads; then
            run_workload asymmetric/datacenter-workloads env ARTIFACT_RUN_DIR="$(run_dir asymmetric datacenter-workloads)" \
                "$SCRIPT_DIR/asymmetric/datacenter-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one asymmetric datacenter-workloads \
                "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended.history" \
                "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended_runs.csv"
        fi
        if want_workload collective-communication-workloads; then
            run_workload asymmetric/collective-communication-workloads env ARTIFACT_RUN_DIR="$(run_dir asymmetric collective-communication-workloads)" \
                "$SCRIPT_DIR/asymmetric/collective-communication-workloads/run_experiments.sh" || failed=1
            ((DRY_RUN)) || import_history_one asymmetric collective-communication-workloads \
                "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended_runs.csv"
        fi
    fi
    if ((failed)); then
        printf 'ERROR: one or more workload groups failed.\n' >&2
        return 1
    fi
}

require_history() {
    local section="$1" workload="$2" need_manifest="${3:-0}" dir
    dir="$(run_dir "$section" "$workload")"
    if [[ -f "$dir/status.json" ]]; then
        python3 "$SCRIPT_DIR/common/run_status.py" check --run-dir "$dir" ||
            die "run is not complete: $dir"
    fi
    [[ -s "$dir/history/all.history" ]] || die "missing $dir/history/all.history; run this group first"
    if [[ "$need_manifest" == "1" ]]; then
        [[ -s "$dir/manifest.csv" ]] || die "missing $dir/manifest.csv; run this group first"
    fi
}

parser_dir() { printf '%s/parser/artifact/%s' "$NS3_ROOT" "$1"; }
plot_dir() { printf '%s/main/plot_artifact/%s' "$MONOREPO" "$1"; }

parse_one() {
    local section="$1" workload="$2" script="$3" dir parser_root
    shift 3
    dir="$(run_dir "$section" "$workload")"
    parser_root="$(parser_dir "$section")"
    python3 "$parser_root/$script" \
        --run-dir "$dir" \
        --ns3-root "$NS3_ROOT" \
        "${DRY_ARGS[@]}" \
        "$@"
}

parse_stage() {
    if ! ((DRY_RUN)); then
        if want_section lossless; then
            want_workload datacenter-workloads && import_history_one lossless datacenter-workloads \
                "$SCRIPT_DIR/lossless/datacenter-workloads/results/lossless_datacenter.history" \
                "$SCRIPT_DIR/lossless/datacenter-workloads/results/lossless_datacenter_runs.csv"
            want_workload collective-communication-workloads && import_history_one lossless collective-communication-workloads \
                "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossless/collective-communication-workloads/extended_runs.csv"
        fi
        if want_section lossy; then
            want_workload datacenter-workloads && import_history_one lossy datacenter-workloads \
                "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossy/datacenter-workloads/extended_runs.csv"
            want_workload collective-communication-workloads && import_history_one lossy collective-communication-workloads \
                "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/lossy/collective-communication-workloads/extended_runs.csv"
        fi
        if want_section asymmetric; then
            want_workload datacenter-workloads && import_history_one asymmetric datacenter-workloads \
                "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended.history" \
                "$SCRIPT_DIR/results/asymmetric/datacenter-workloads/extended_runs.csv"
            want_workload collective-communication-workloads && import_history_one asymmetric collective-communication-workloads \
                "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended.history" \
                "$SCRIPT_DIR/results/asymmetric/collective-communication-workloads/extended_runs.csv"
        fi
    fi
    if want_section lossless; then
        if want_workload datacenter-workloads; then
            ((DRY_RUN)) || require_history lossless datacenter-workloads 1
            parse_one lossless datacenter-workloads parse_fig04_lossless_dcn_p99_fct.py
            parse_one lossless datacenter-workloads parse_fig05_lossless_ooo_degree.py
            parse_one lossless datacenter-workloads parse_fig06_lossless_pfc_pause_duration.py
            parse_one lossless datacenter-workloads parse_fig09_lossless_queue_per_pfc_event.py
            parse_one lossless datacenter-workloads parse_tbl04_lossless_avg_egress_queue.py
            parse_one lossless datacenter-workloads parse_tbl05_lossless_spine_pause_balance.py
        fi
        if want_workload collective-communication-workloads; then
            if ! ((DRY_RUN)); then
                require_history lossless collective-communication-workloads 1
                require_history lossless datacenter-workloads 1
            fi
            parse_one lossless collective-communication-workloads parse_fig07_lossless_ai_collective_cct.py
            parse_one lossless collective-communication-workloads parse_fig08_lossless_pfc_incast_degree.py \
                --datacenter-run-dir "$(run_dir lossless datacenter-workloads)"
            parse_one lossless collective-communication-workloads parse_fig10_lossless_spine_queue_timeseries.py
        fi
    fi
    if want_section lossy; then
        if want_workload datacenter-workloads; then
            ((DRY_RUN)) || require_history lossy datacenter-workloads 1
            parse_one lossy datacenter-workloads parse_fig11_lossy_dcn_p99_fct_leafspine.py
            parse_one lossy datacenter-workloads parse_fig12_lossy_dcn_p99_fct_fattree.py
        fi
        if want_workload collective-communication-workloads; then
            ((DRY_RUN)) || require_history lossy collective-communication-workloads 1
            parse_one lossy collective-communication-workloads parse_fig13_lossy_ai_collective_cct.py
        fi
    fi
    if want_section asymmetric; then
        if want_workload datacenter-workloads; then
            ((DRY_RUN)) || require_history asymmetric datacenter-workloads 1
            parse_one asymmetric datacenter-workloads parse_fig14_asym_dcn_fct.py
            parse_one asymmetric datacenter-workloads parse_fig15_asym_ooo_retransmission.py
            parse_one asymmetric datacenter-workloads parse_fig16_asym_packet_trim_rto.py
        fi
        if want_workload collective-communication-workloads; then
            ((DRY_RUN)) || require_history asymmetric collective-communication-workloads 1
            parse_one asymmetric collective-communication-workloads parse_fig17_asym_ai_collective_cct.py
        fi
    fi
}

plot_one() {
    local section="$1" workload="$2" script="$3" output="$4" dir plot_root
    shift 4
    dir="$(run_dir "$section" "$workload")"
    plot_root="$(plot_dir "$section")"
    python3 "$plot_root/$script" \
        --input-dir "$dir/json/$output" \
        --output-dir "$dir/figures" \
        "${DRY_ARGS[@]}" \
        "$@"
}

plot_stage() {
    if want_section lossless; then
        if want_workload datacenter-workloads; then
            plot_one lossless datacenter-workloads plot_fig04_lossless_dcn_p99_fct.py fig04_lossless_dcn_p99_fct
            plot_one lossless datacenter-workloads plot_fig05_lossless_ooo_degree.py fig05_lossless_ooo_degree
            plot_one lossless datacenter-workloads plot_fig06_lossless_pfc_pause_duration.py fig06_lossless_pfc_pause_duration
            plot_one lossless datacenter-workloads plot_fig09_lossless_queue_per_pfc_event.py fig09_lossless_queue_per_pfc_event
        fi
        if want_workload collective-communication-workloads; then
            plot_one lossless collective-communication-workloads plot_fig07_lossless_ai_collective_cct.py fig07_lossless_ai_collective_cct
            plot_one lossless collective-communication-workloads plot_fig08_lossless_pfc_incast_degree.py fig08_lossless_pfc_incast_degree
            plot_one lossless collective-communication-workloads plot_fig10_lossless_spine_queue_timeseries.py fig10_lossless_spine_queue_timeseries --spine-id "$SPINE_ID"
        fi
    fi
    if want_section lossy; then
        if want_workload datacenter-workloads; then
            plot_one lossy datacenter-workloads plot_fig11_lossy_dcn_p99_fct_leafspine.py fig11_lossy_dcn_p99_fct_leafspine
            plot_one lossy datacenter-workloads plot_fig12_lossy_dcn_p99_fct_fattree.py fig12_lossy_dcn_p99_fct_fattree
        fi
        if want_workload collective-communication-workloads; then
            plot_one lossy collective-communication-workloads plot_fig13_lossy_ai_collective_cct.py fig13_lossy_ai_collective_cct
        fi
    fi
    if want_section asymmetric; then
        if want_workload datacenter-workloads; then
            plot_one asymmetric datacenter-workloads plot_fig14_asym_dcn_fct.py fig14_asym_dcn_fct
            plot_one asymmetric datacenter-workloads plot_fig15_asym_ooo_retransmission.py fig15_asym_ooo_retransmission
            plot_one asymmetric datacenter-workloads plot_fig16_asym_packet_trim_rto.py fig16_asym_packet_trim_rto
        fi
        if want_workload collective-communication-workloads; then
            plot_one asymmetric collective-communication-workloads plot_fig17_asym_ai_collective_cct.py fig17_asym_ai_collective_cct
        fi
    fi
}

status_one() {
    local section="$1" workload="$2" dir
    dir="$(run_dir "$section" "$workload")"
    printf '[%s/%s]\n' "$section" "$workload"
    if [[ -f "$dir/status.json" ]]; then
        python3 "$SCRIPT_DIR/common/run_status.py" show --run-dir "$dir"
    elif [[ -s "$dir/history/all.history" ]]; then
        printf 'run_dir=%s\nstate=legacy-history\n' "$dir"
    else
        printf 'run_dir=%s\nstate=not-started\n' "$dir"
    fi
}

status_stage() {
    local section
    for section in lossless lossy asymmetric; do
        if want_section "$section"; then
            if want_workload datacenter-workloads; then
                status_one "$section" datacenter-workloads
            fi
            if want_workload collective-communication-workloads; then
                status_one "$section" collective-communication-workloads
            fi
        fi
    done
}

case "$STAGE" in
    run) run_stage ;;
    parse) parse_stage ;;
    plot) plot_stage ;;
    status) status_stage ;;
    all) run_stage; parse_stage; plot_stage ;;
esac
