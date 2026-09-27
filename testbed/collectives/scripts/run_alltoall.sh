#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/mpi_env.sh"
setup_mpi_for_run "$@"
exec python3 "$(dirname "${BASH_SOURCE[0]}")/run.py" alltoall "$@"
