#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS="${ARTIFACT_DIR}/results/lossy/datacenter-workloads"
SELECT=(--figure figure11 --figure figure12)

exec "${ARTIFACT_DIR}/common/parse_paper_matrix.sh" --results-dir "$RESULTS" "${SELECT[@]}" "$@"
