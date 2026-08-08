#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/asymmetric/datacenter-workloads"
SELECT=(--figure figure14 --figure figure15 --figure figure16)

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: ./plot_results.sh [--dry-run]"
    exit 0
fi
if [[ "${1:-}" == "--dry-run" ]]; then
    [[ "$#" -eq 1 ]] || { echo "Usage: ./plot_results.sh [--dry-run]" >&2; exit 1; }
    exec "${ARTIFACT_DIR}/common/plot_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" --dry-run
fi
[[ "$#" -eq 0 ]] || { echo "Usage: ./plot_results.sh [--dry-run]" >&2; exit 1; }
exec "${ARTIFACT_DIR}/common/plot_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}"
