#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/lossy/collective-communication-workloads"
SELECT=(--figure figure13)

exec "${ARTIFACT_DIR}/common/parse_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" "$@"
