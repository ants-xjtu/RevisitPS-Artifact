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

check_mpi_toolchain() {
  # Custom Dockerfiles may use a different toolchain preparation process.
  [[ "${ARTIFACT_DOCKERFILE:-testbed/docker/Dockerfile}" == testbed/docker/Dockerfile ]] || return 0
  if [[ ! -f build/mpi-toolchain/openmpi-4.1.7rc1/bin/mpicxx ||
        ! -s build/mpi-toolchain/SHA256SUMS ]]; then
    echo 'The default image requires an exported MPI toolchain. From the testbed directory, run:' >&2
    printf '  PYTHONPATH=%q python3 docker/export_mpi_toolchain.py --deployment %q\n' "$PWD" "$ARTIFACT_DEPLOYMENT_PATH" >&2
    echo 'Then retry ./run.sh build. The export requires Python dependencies from docker/requirements.lock.txt and SSH access to the configured launcher.' >&2
    return 1
  fi
  (cd build/mpi-toolchain && sha256sum --quiet -c SHA256SUMS) || {
    echo 'MPI toolchain checksum verification failed; inspect build/mpi-toolchain before rebuilding.' >&2
    return 1
  }
}
# Fail before submodule preparation when the explicit build lacks its input.
if [[ ${1:-} == build ]]; then
  check_mpi_toolchain
fi
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
container_id=
experiment=
run_id=
previous=
for argument in "$@"; do
  [[ "$previous" != --stage ]] || stage=$argument
  [[ "$previous" != --experiment ]] || experiment=$argument
  [[ "$previous" != --run-id ]] || run_id=$argument
  [[ "$argument" != --stage=* ]] || stage=${argument#--stage=}
  [[ "$argument" != --experiment=* ]] || experiment=${argument#--experiment=}
  [[ "$argument" != --run-id=* ]] || run_id=${argument#--run-id=}
  [[ "$argument" != --dry-run ]] || offline=true
  previous=$argument
done

# Do not split online and offline results between an old bind mount and the new
# volume. Leave a running legacy console untouched until it can be migrated.
if [[ "$offline" != true ]]; then
  container_id=$("${compose[@]}" ps -q artifact)
  if [[ -n "$container_id" ]]; then
    results_mount_type=$(docker inspect "$container_id" --format '{{range .Mounts}}{{if eq .Destination "/opt/artifact/testbed/results"}}{{.Type}}{{end}}{{end}}')
    if [[ "$results_mount_type" != volume ]]; then
      echo 'The console still uses the old results mount. After active work finishes, run ./run.sh build and remove the old console; the next hardware run creates its replacement.' >&2
      exit 1
    fi
  fi
fi

# Export only this invocation's run, as the calling host user. Read the actual
# console's mounts for online stages; offline stages use the shared results volume.
export_results() {
  [[ "$offline" != true && "$experiment" =~ ^(dcn_workload|ai_workload)$ &&
     "$run_id" =~ ^[a-zA-Z0-9_-]+$ ]] || return 0
  local source="/opt/artifact/testbed/results/$experiment" destination="$PWD/results/$experiment"
  local reader=("${compose[@]}" run --rm --no-deps --pull never -T --entrypoint sh artifact)
  if [[ -n "${container_id:-}" ]]; then
    reader=(docker exec "$container_id" sh)
  fi
  mkdir -p "$destination" || return 1
  # An early failure or a status query may have no run directory yet. Emit a
  # valid empty archive then, without hiding actual transport/read errors.
  "${reader[@]}" -c '
    if [ -d "$1/$2" ]; then
      exec tar -C "$1" -cf - -- "$2"
    else
      exec tar -cf - -T /dev/null
    fi
  ' sh "$source" "$run_id" |
    tar --extract --file=- --no-same-owner --no-same-permissions --directory="$destination" || return 1
  printf 'Results exported to %s/%s (if created)\n' "$destination" "$run_id" >&2
}

run_and_export() {
  local result=0
  "$@" || result=$?
  if ! export_results; then
    echo 'Result export failed; container results are retained. Retry with --stage status.' >&2
    [[ "$result" != 0 ]] || result=1
  fi
  return "$result"
}
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
  run_and_export "${compose[@]}" run --rm --no-deps --pull never -T artifact "${entry[@]}" "$@"
  exit $?
fi
container_id=$("${compose[@]}" ps -q artifact)
if [[ -z "$container_id" ]]; then
  check_mpi_toolchain
  "${compose[@]}" up -d --build
fi
container_id=$("${compose[@]}" ps -q artifact)
image_id=$(docker inspect "$container_id" --format '{{.Image}}')
run_and_export "${compose[@]}" exec -T -e ARTIFACT_IMAGE_ID="$image_id" artifact "${entry[@]}" "$@"
