#!/usr/bin/env bash
set -euo pipefail

testbed_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="${testbed_root}${PYTHONPATH:+:${PYTHONPATH}}"
helper="${testbed_root}/experiments/ai_workload/scripts/connectivity_support.py"
log_info() { printf '[INFO] %s\n' "$*"; }
parse_endpoint() { printf '%s %s\n' "${1%:*}" "${1##*:}"; }
detect_gid_index_for_endpoint_v2() { python3 "${helper}" gid "$1"; }
run_mpi() { python3 "${helper}" launch "$@"; }

selected_endpoints=""
outdir=""
binary_path=""
mixed_binary_path=""
dry_run=0
skip_build=0
skip_sync=0
use_rdma_cm="${USE_RDMA_CM:-0}"
bench=jct
bw_options=()
warmup=""
iters=""
size_bytes=""
timeout_seconds=30
same_host_only=0
jobs=1
gid_index=""
auto_detect_gid=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bench)
      bench="$2"
      shift 2
      ;;
    --mode|--inflight|--sig-interval|--write-chunk|--write-notify)
      bw_options+=("$1" "$2")
      shift 2
      ;;
    --selected-endpoints)
      selected_endpoints="$2"
      shift 2
      ;;
    --outdir)
      outdir="$2"
      shift 2
      ;;
    --binary)
      binary_path="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    --skip-sync)
      skip_sync=1
      shift
      ;;
    --use-rdma-cm)
      use_rdma_cm="$2"
      shift 2
      ;;
    --warmup)
      warmup="$2"
      shift 2
      ;;
    --iters)
      iters="$2"
      shift 2
      ;;
    --size-bytes|--sizes)
      size_bytes="$2"
      shift 2
      ;;
    --timeout-seconds)
      timeout_seconds="$2"
      shift 2
      ;;
    --same-host-only)
      same_host_only=1
      shift
      ;;
    --jobs)
      jobs="$2"
      shift 2
      ;;
    --gid-index)
      gid_index="$2"
      shift 2
      ;;
    --no-auto-gid-detect)
      auto_detect_gid=0
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

case "${bench}" in
  jct)
    workload=alltoall
    warmup="${warmup:-2}"
    iters="${iters:-5}"
    size_bytes="${size_bytes:-64}"
    if (( ${#bw_options[@]} )); then
      echo 'Bandwidth options require --bench bw' >&2
      exit 1
    fi
    ;;
  bw)
    workload=p2p_bw
    warmup="${warmup:-200}"
    iters="${iters:-2000}"
    size_bytes="${size_bytes:-8M,4M,2M,1M,512K,256K,128K,64K}"
    if [[ "${use_rdma_cm}" != 0 ]]; then
      echo '--bench bw uses verbs QPs and does not support --use-rdma-cm' >&2
      exit 1
    fi
    ;;
  *) echo '--bench must be jct or bw' >&2; exit 1 ;;
esac

[[ -n "${selected_endpoints}" ]]
[[ -f "${selected_endpoints}" ]]
[[ -n "${outdir}" ]]
if ! [[ "${jobs}" =~ ^[0-9]+$ ]] || [[ "${jobs}" == "0" ]]; then
  echo "--jobs must be a positive integer" >&2
  exit 1
fi
if [[ -n "${gid_index}" ]] && ! [[ "${gid_index}" =~ ^[0-9]+$ ]]; then
  echo "--gid-index must be a non-negative integer" >&2
  exit 1
fi

mkdir -p "${outdir}"
csv_file="${outdir}/pair_connectivity.csv"
same_host_failures="${outdir}/same_host_failures.txt"

mapfile -t endpoints < <(awk 'NF>0' "${selected_endpoints}")
if (( ${#endpoints[@]} < 2 )); then
  echo "Need at least 2 endpoints in ${selected_endpoints}" >&2
  exit 1
fi

if [[ ${dry_run} -eq 0 ]]; then
  mkdir -p "${ARTIFACT_LOCK_DIR:-${testbed_root}/runtime/locks}"
  exec 9>"${ARTIFACT_LOCK_DIR:-${testbed_root}/runtime/locks}/testbed.lock"
  flock -n 9 || { echo 'Testbed is already in use' >&2; exit 1; }
  binary_path="$(python3 "${helper}" prepare "${workload}" "${selected_endpoints}" "${skip_build}" "${skip_sync}" "${binary_path}")"
fi

prepare_mixed_binary=0
if [[ "${bench}" == jct && ${dry_run} -eq 0 && -z "${gid_index}" && ${auto_detect_gid} -eq 1 ]]; then
  declare -A gid_seen=()
  for ep in "${endpoints[@]}"; do
    gid_val="$(detect_gid_index_for_endpoint_v2 "${ep}" || true)"
    if [[ -n "${gid_val}" ]]; then
      gid_seen["${gid_val}"]=1
    fi
  done
  if (( ${#gid_seen[@]} > 1 )); then
    prepare_mixed_binary=1
  fi
fi

if [[ ${prepare_mixed_binary} -eq 1 ]]; then
  mixed_binary_path="$(python3 "${helper}" prepare connectivity_ring "${selected_endpoints}" "${skip_build}" "${skip_sync}" "")"
  log_info "Mixed GID detected in endpoint set, cross-gid pairs will use ringallreduce binary"
fi

printf 'src_host,src_dev,dst_host,dst_dev,status,rc,log_path\n' > "${csv_file}"
: > "${same_host_failures}"

sanitize() {
  local s="$1"
  s="${s//:/_}"
  printf '%s\n' "${s}"
}

run_pair() {
  local src_ep="$1"
  local dst_ep="$2"
  local csv_out="$3"
  local same_host_out="$4"

  read -r src_host src_dev < <(parse_endpoint "${src_ep}")
  read -r dst_host dst_dev < <(parse_endpoint "${dst_ep}")

  local log_name
  log_name="pair_$(sanitize "${src_host}:${src_dev}")_to_$(sanitize "${dst_host}:${dst_dev}").log"
  local log_path="${outdir}/${log_name}"

  local src_gid="${gid_index}"
  local dst_gid="${gid_index}"
  if [[ ${dry_run} -eq 0 && -z "${gid_index}" && ${auto_detect_gid} -eq 1 ]]; then
    src_gid="$(detect_gid_index_for_endpoint_v2 "${src_ep}")" || {
      printf '%s,%s,%s,%s,FAIL,98,%s\n' \
        "${src_host}" "${src_dev}" "${dst_host}" "${dst_dev}" "${log_path}" > "${csv_out}"
      printf '[ERROR] failed to detect GID for %s:%s\n' "${src_host}" "${src_dev}" > "${log_path}"
      : > "${same_host_out}"
      return 0
    }
    dst_gid="$(detect_gid_index_for_endpoint_v2 "${dst_ep}")" || {
      printf '%s,%s,%s,%s,FAIL,98,%s\n' \
        "${src_host}" "${src_dev}" "${dst_host}" "${dst_dev}" "${log_path}" > "${csv_out}"
      printf '[ERROR] failed to detect GID for %s:%s\n' "${dst_host}" "${dst_dev}" > "${log_path}"
      : > "${same_host_out}"
      return 0
    }
  fi

  local host_spec map_by dev_map gid_map pair_binary
  if [[ "${src_host}" == "${dst_host}" ]]; then
    host_spec="${src_host}:2"
    map_by="ppr:2:node"
    dev_map="${src_host}:${src_dev},${dst_dev}"
    gid_map="${src_host}:${src_dev}=${src_gid},${dst_dev}=${dst_gid}"
  else
    host_spec="${src_host},${dst_host}"
    map_by="ppr:1:node"
    dev_map="${src_host}:${src_dev}|${dst_host}:${dst_dev}"
    gid_map="${src_host}:${src_dev}=${src_gid}|${dst_host}:${dst_dev}=${dst_gid}"
  fi
  pair_binary="${binary_path}"
  if [[ -z "${pair_binary}" ]]; then
    if [[ "${bench}" == bw ]]; then
      pair_binary=mpi_verbs_p2p_bw
    else
      pair_binary=mpi_verbs_global_alltoall
    fi
  fi
  local -a cmd=(run_mpi "${timeout_seconds}" --host "${host_spec}" -np 2
                --map-by "${map_by}")
  if [[ "${bench}" == bw ]]; then
    cmd+=(-x "IB_DEV_MAP_BY_HOST=" -x "IB_DEV_MAP=${src_dev},${dst_dev}")
  else
    cmd+=(-x "IB_DEV_MAP_BY_HOST=${dev_map}")
  fi
  if [[ "${bench}" == jct ]]; then
    cmd+=(-x "USE_RDMA_CM=${use_rdma_cm}")
  fi
  if [[ -n "${src_gid}" && -n "${dst_gid}" && "${src_gid}" != "${dst_gid}" ]]; then
    cmd+=(-x "GID_INDEX_BY_HOST_DEV=${gid_map}")
    if [[ "${bench}" == jct ]]; then
      pair_binary="${mixed_binary_path:-${binary_path}}"
    fi
  elif [[ -n "${src_gid}" ]]; then
    cmd+=(-x "GID_INDEX=${src_gid}")
  fi
  cmd+=("${pair_binary}" --bench "${bench}" --sizes "${size_bytes}"
        --warmup "${warmup}" --iters "${iters}")
  if [[ "${bench}" == bw ]]; then
    cmd+=("${bw_options[@]}")
  else
    cmd+=(--groupsize 2)
  fi

  if [[ ${dry_run} -eq 1 ]]; then
    printf 'dry-run: %s:%s -> %s:%s\n' "${src_host}" "${src_dev}" "${dst_host}" "${dst_dev}" > "${log_path}"
    printf 'command: ' >> "${log_path}"
    printf '%q ' "${cmd[@]}" >> "${log_path}"
    printf '\n' >> "${log_path}"
    printf '%s,%s,%s,%s,DRY_RUN,0,%s\n' \
      "${src_host}" "${src_dev}" "${dst_host}" "${dst_dev}" "${log_path}" > "${csv_out}"
    : > "${same_host_out}"
    return 0
  fi

  local rc
  set +e
  { "${cmd[@]}" > "${log_path}" 2>&1; rc=$?; } 2>/dev/null
  set -e

  local status="FAIL"
  if [[ ${rc} -eq 0 ]]; then
    status="PASS"
  fi

  printf '%s,%s,%s,%s,%s,%d,%s\n' \
    "${src_host}" "${src_dev}" "${dst_host}" "${dst_dev}" "${status}" "${rc}" "${log_path}" > "${csv_out}"

  : > "${same_host_out}"
  if [[ "${status}" == "FAIL" && "${src_host}" == "${dst_host}" ]]; then
    printf '%s: %s <-> %s\n' "${src_host}" "${src_dev}" "${dst_dev}" > "${same_host_out}"
  fi
}

pair_src=()
pair_dst=()
for (( i = 0; i < ${#endpoints[@]}; i++ )); do
  for (( j = i + 1; j < ${#endpoints[@]}; j++ )); do
    if [[ ${same_host_only} -eq 1 ]]; then
      read -r h1 _ < <(parse_endpoint "${endpoints[$i]}")
      read -r h2 _ < <(parse_endpoint "${endpoints[$j]}")
      if [[ "${h1}" != "${h2}" ]]; then
        continue
      fi
    fi
    pair_src+=("${endpoints[$i]}")
    pair_dst+=("${endpoints[$j]}")
  done
done

tmpdir="$(mktemp -d "${outdir}/pair_tmp.XXXXXX")"
trap 'rm -rf "${tmpdir}"' EXIT

worker_pids=()
for (( idx = 0; idx < ${#pair_src[@]}; idx++ )); do
  csv_tmp="${tmpdir}/result_${idx}.csv"
  fail_tmp="${tmpdir}/same_host_${idx}.txt"
  run_pair "${pair_src[$idx]}" "${pair_dst[$idx]}" "${csv_tmp}" "${fail_tmp}" &
  worker_pids+=("$!")
  while (( $(jobs -rp | wc -l) >= jobs )); do
    wait -n || true
  done
done
worker_failed=0
for pid in "${worker_pids[@]}"; do
  wait "$pid" || worker_failed=1
done

printf 'src_host,src_dev,dst_host,dst_dev,status,rc,log_path\n' > "${csv_file}"
: > "${same_host_failures}"
total="${#pair_src[@]}"
fail=0
missing=0
for (( idx = 0; idx < ${#pair_src[@]}; idx++ )); do
  csv_tmp="${tmpdir}/result_${idx}.csv"
  fail_tmp="${tmpdir}/same_host_${idx}.txt"
  if [[ -s "${csv_tmp}" && -f "${csv_tmp}" ]]; then
    line="$(cat "${csv_tmp}")"
    printf '%s\n' "${line}" >> "${csv_file}"
    if [[ "$(awk -F',' '{print $5}' <<< "${line}")" == "FAIL" ]]; then
      fail=$((fail + 1))
    fi
  else
    missing=$((missing + 1))
    echo "Missing result for ${pair_src[$idx]} -> ${pair_dst[$idx]}" >&2
  fi
  if [[ -s "${fail_tmp}" ]]; then
    cat "${fail_tmp}" >> "${same_host_failures}"
  fi
done

if [[ ! -s "${same_host_failures}" ]]; then
  printf '# no same-host failures\n' > "${same_host_failures}"
fi

log_info "Wrote ${csv_file}"
log_info "Wrote ${same_host_failures}"
log_info "pairs=${total} fail=${fail} missing=${missing}"
if (( fail > 0 || missing > 0 || worker_failed > 0 )); then
  exit 1
fi
