#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source "$root/scripts/mpi_env.sh"
setup_mpi
mkdir -p build
compiler="$MPICXX"
printf 'MPI compiler: %s\n' "$compiler"
for name in mpi_verbs_p2p_ring4 mpi_verbs_global_alltoall mpi_verbs_global_alltoallv; do
  sources=("src/${name}.cpp")
  if [[ "$name" == mpi_verbs_global_alltoallv ]]; then
    sources+=(src/zipfian_incast_pattern.cpp)
  fi
  "$compiler" -O2 -std=c++11 -o "build/$name" "${sources[@]}" -libverbs -lrdmacm
done
printf 'Built three executables in %s/build\n' "$root"
