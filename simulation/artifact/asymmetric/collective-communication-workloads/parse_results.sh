#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/asymmetric/collective-communication-workloads"
SELECT=(--figure figure17)

exec "${ARTIFACT_DIR}/common/parse_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" "$@"
