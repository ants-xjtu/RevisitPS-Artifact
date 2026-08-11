#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec "${ARTIFACT_DIR}/run_artifact.sh" \
    --section lossy \
    --workload collective-communication-workloads \
    --stage plot \
    "$@"
