#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
repo=$(cd .. && pwd)
export ARTIFACT_UID=$(id -u) ARTIFACT_GID=$(id -g)
export ARTIFACT_DEPLOYMENT_PATH=${ARTIFACT_DEPLOYMENT_PATH:-$PWD/deployment/deployment.local.yaml}
if [[ ! -f "$ARTIFACT_DEPLOYMENT_PATH" ]]; then
  export ARTIFACT_DEPLOYMENT_PATH=$PWD/deployment/deployment.yaml
fi
compose=(docker compose -f "$PWD/docker/compose.yaml")
# submodule update follows the parent's gitlink, never a branch tip.
git -C "$repo" submodule update --init -- testbed/experiments/dcn_workload/sources/perftest
expected=$(git -C "$repo" ls-files -s testbed/experiments/dcn_workload/sources/perftest | awk '$1==160000 {print $2}')
export PERFTEST_COMMIT=$(git -C experiments/dcn_workload/sources/perftest rev-parse HEAD)
[[ -n "$expected" && "$PERFTEST_COMMIT" == "$expected" ]] || { echo 'perftest gitlink mismatch' >&2; exit 1; }
[[ -z "$(git -C experiments/dcn_workload/sources/perftest status --porcelain --untracked-files=all --ignored)" ]] || { echo 'perftest source is dirty' >&2; exit 1; }
export PROJECT_VERSION=$(git -C "$repo" describe --always --dirty)
if [[ ${1:-} == build ]]; then
  exec "${compose[@]}" build
fi
if [[ ${1:-} == monitor ]]; then
  shift
  run_id= switch=
  while (($#)); do
    case "$1" in
      --run-id) run_id=$2; shift 2;;
      --switch) switch=$2; shift 2;;
      *) echo "Unknown monitor argument: $1" >&2; exit 2;;
    esac
  done
  [[ "$run_id" =~ ^[a-zA-Z0-9_-]+$ && "$switch" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
  exec "${compose[@]}" exec artifact tmux attach-session -t "artifact-$run_id-$switch"
fi
stage=all
offline=false
previous=
for argument in "$@"; do
  [[ "$previous" != --stage ]] || stage=$argument
  [[ "$argument" != --stage=* ]] || stage=${argument#--stage=}
  [[ "$argument" != --dry-run ]] || offline=true
  previous=$argument
done
if [[ "$stage" != parse && "$stage" != plot && "$stage" != status && "$offline" != true ]]; then
  export ARTIFACT_AGENT_SOCKET=${ARTIFACT_AGENT_SOCKET:-${SSH_AUTH_SOCK:-}}
  [[ -S "$ARTIFACT_AGENT_SOCKET" ]] || { echo 'A dedicated SSH agent socket is required' >&2; exit 1; }
  SSH_AUTH_SOCK=$ARTIFACT_AGENT_SOCKET ssh-add -l >/dev/null
  : "${ARTIFACT_SSH_CONFIG_PATH:?Set verified SSH config path}"
  : "${ARTIFACT_KNOWN_HOSTS_PATH:?Set verified known_hosts path}"
  [[ -r "$ARTIFACT_SSH_CONFIG_PATH" && -r "$ARTIFACT_KNOWN_HOSTS_PATH" ]] || exit 1
fi
mkdir -p results build runtime/locks
# Keep the console container alive. Do not replace it because an offline stage
# no longer exports SSH mount variables. Rebuild/recreate explicitly between runs.
entry=(python -m framework.cli)
if [[ ${1:-} != diagnose && ${1:-} != nic ]]; then
  entry+=(--deployment deployment/deployment.runtime.yaml)
fi
if [[ "$stage" == parse || "$stage" == plot || "$stage" == status || "$offline" == true ]]; then
  # Offline operations must not recreate a live console or build software.
  docker image inspect "${ARTIFACT_IMAGE:-revisitps-testbed:local}" >/dev/null 2>&1 || {
    echo 'Offline stages require a prebuilt image; run ./run.sh build first' >&2; exit 1;
  }
  exec "${compose[@]}" run --rm --no-deps --pull never -T artifact "${entry[@]}" "$@"
fi
container_id=$("${compose[@]}" ps -q artifact)
if [[ -z "$container_id" ]]; then
  "${compose[@]}" up -d --build
fi
container_id=$("${compose[@]}" ps -q artifact)
image_id=$(docker inspect "$container_id" --format '{{.Image}}')
exec "${compose[@]}" exec -T -e ARTIFACT_IMAGE_ID="$image_id" artifact "${entry[@]}" "$@"
