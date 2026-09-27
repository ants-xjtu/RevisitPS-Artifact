#!/usr/bin/env bash

setup_mpi() {
  local compiler="${MPICXX:-}"
  if [[ -z "$compiler" ]]; then
    if [[ -n "${MPI_HOME:-}" ]]; then
      compiler="${MPI_HOME}/bin/mpicxx"
    elif command -v mpicxx >/dev/null 2>&1; then
      compiler="$(command -v mpicxx)"
    elif [[ -x "${HOME}/ompi/bin/mpicxx" ]]; then
      compiler="${HOME}/ompi/bin/mpicxx"
    else
      printf 'MPI compiler not found. Set MPI_HOME=/path/to/openmpi or MPICXX=/path/to/mpicxx.\n' >&2
      return 1
    fi
  fi
  local resolved
  resolved="$(command -v "$compiler")" || {
    printf 'MPI compiler is not executable: %s\n' "$compiler" >&2
    return 1
  }
  local mpi_bin
  mpi_bin="$(cd "$(dirname "$resolved")" && pwd)"
  export MPICXX="${mpi_bin}/$(basename "$resolved")"
  export PATH="${mpi_bin}:${PATH}"
  if [[ "${1:-build}" == run && ! -x "${mpi_bin}/mpirun" ]]; then
    printf 'Matching mpirun not found in %s\n' "$mpi_bin" >&2
    return 1
  fi
}

setup_mpi_for_run() {
  local argument
  for argument in "$@"; do
    case "$argument" in
      --dry-run|--help|-h) return 0 ;;
    esac
  done
  setup_mpi run
}
