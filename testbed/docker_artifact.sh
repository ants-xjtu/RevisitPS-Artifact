#!/usr/bin/env bash
# Compatibility: the old --experiment selected the network mode.
set -euo pipefail
args=(--experiment dcn_workload)
while (($#)); do
  case "$1" in
    --experiment) args+=(--network-mode "$2"); shift 2;;
    --experiment=*) args+=(--network-mode "${1#*=}"); shift;;
    build|monitor) exec "$(dirname "$0")/run.sh" "$@";;
    *) args+=("$1"); shift;;
  esac
done
exec "$(dirname "$0")/run.sh" "${args[@]}"
