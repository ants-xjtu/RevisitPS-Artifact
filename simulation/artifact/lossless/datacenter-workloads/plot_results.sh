#!/usr/bin/env bash
set -euo pipefail

# Parser JSON -> plot workspace targets -> final PDFs.
# This script never runs ns-3 and never invokes a parser.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
MONOREPO="$(cd "${NS3_ROOT}/.." && pwd)/plot"
RESULTS="${SCRIPT_DIR}/results"
JSON_ROOT="${RESULTS}/json"
FIGURES="${RESULTS}/figures"
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: ./artifact/lossless/datacenter-workloads/plot_results.sh [--dry-run]

Plots:
  Figure 4  //main/plot_sample:plot_dcn_fct
  Figure 5  //main/plot_sample:plot_dcn_ooo
  Figure 6  //main/plot_sample:plot_dcn_pfc_trigger

Table 4 is produced by the parse stage and has no plotting step.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
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

[[ -f "${MONOREPO}/main/plot_sample/BUILD.bazel" ]] || die "missing plot workspace: ${MONOREPO}"

run_plot() {
    local target="$1"
    local input="$2"
    if ((DRY_RUN)); then
        printf 'PLOT_COMMAND bazel run %q -- %q\n' "$target" "$input"
        return
    fi
    [[ -e "$input" ]] || die "missing parser JSON input: ${input}"
    (cd "$MONOREPO" && bazel run "$target" -- "$input")
}

run_plot //main/plot_sample:plot_dcn_fct "${JSON_ROOT}/figure4"
run_plot //main/plot_sample:plot_dcn_ooo "${JSON_ROOT}/figure5/figure5.json"
run_plot //main/plot_sample:plot_dcn_pfc_trigger "${JSON_ROOT}/figure6"

if ((DRY_RUN)); then
    exit 0
fi

mkdir -p "$FIGURES"
cp "${JSON_ROOT}/figure4/DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0_p99.pdf" "${FIGURES}/figure4a_p99_fct.pdf"
cp "${JSON_ROOT}/figure4/DATA_TOPO_fat_k8_100G_OS1_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0_p99.pdf" "${FIGURES}/figure4b_p99_fct.pdf"
cp "${JSON_ROOT}/figure5/figure5_dist_cdf.pdf" "${FIGURES}/figure5_ooo_degree.pdf"
cp "${JSON_ROOT}/figure6/grouped_pfc_comparison_total_duration_ns.pdf" "${FIGURES}/figure6_pause_duration.pdf"

echo "Final PDFs written below ${FIGURES}"
