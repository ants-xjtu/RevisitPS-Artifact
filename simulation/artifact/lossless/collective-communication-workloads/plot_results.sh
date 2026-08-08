#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/lossless/collective-communication-workloads"
SELECT=(--figure figure7 --figure figure8 --figure figure9 --figure figure10 --figure table5)
PLOT_ARGS=()

while (($#)); do
    case "$1" in
        --dry-run)
            PLOT_ARGS+=(--dry-run)
            shift
            ;;
        --spine-id)
            (($# >= 2)) || { echo "ERROR: --spine-id requires a value" >&2; exit 1; }
            PLOT_ARGS+=(--spine-id "$2")
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./plot_results.sh [--dry-run] [--spine-id ID]"
            exit 0
            ;;
        *)
            echo "ERROR: unknown option: $1" >&2
            exit 1
            ;;
    esac
done

exec "${ARTIFACT_DIR}/common/plot_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" "${PLOT_ARGS[@]}"
