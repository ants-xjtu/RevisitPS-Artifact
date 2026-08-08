#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/lossless/collective-communication-workloads"
SELECT=(--figure figure7 --figure figure8 --figure figure9 --figure figure10 --figure table5)

exec "${ARTIFACT_DIR}/common/parse_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" "$@"
