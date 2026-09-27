#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
source scripts/engines/lib/common.sh

selected_endpoints=""
hosts_csv=""
outdir=""
dry_run=0
skip_sync=0
use_rdma_cm="${USE_RDMA_CM:-0}"
only_np=""
np2_fast=0
size_bytes=3145728
warmup=10
iters=100
jct_mode=""
inflight_per_peer=""
signal_interval=""
bind_to="core"
gid_index=""
auto_detect_gid=1
total_np=""
declare -a group_specs=()
declare -a group_names=()
declare -a group_nps=()
declare -a group_map_bys=()
declare -a group_dev_maps=()
declare -a group_rankfiles=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --selected-endpoints)
      selected_endpoints="$2"
      shift 2
      ;;
    --hosts)
      hosts_csv="$2"
      shift 2
      ;;
    --outdir)
      outdir="$2"
      shift 2
      ;;
    --total-np)
      total_np="$2"
      shift 2
      ;;
    --group)
      group_specs+=("$2")
      shift 2
      ;;
    --dry-run)
      dry_run=1
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
    --only-np)
      only_np="$2"
      shift 2
      ;;
    --np2-fast)
      np2_fast=1
      shift
      ;;
    --size-bytes)
      size_bytes="$2"
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
    --jct-mode)
      jct_mode="$2"
      shift 2
      ;;
    --inflight-per-peer)
      inflight_per_peer="$2"
      shift 2
      ;;
    --signal-interval)
      signal_interval="$2"
      shift 2
      ;;
    --bind-to)
      bind_to="$2"
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

[[ -n "${outdir}" ]]
if (( ${#group_specs[@]} == 0 )); then
  [[ -n "${selected_endpoints}" ]]
  [[ -f "${selected_endpoints}" ]]
else
  [[ -n "${hosts_csv}" ]]
fi
if [[ -n "${only_np}" && "${only_np}" != "2" && "${only_np}" != "4" && "${only_np}" != "8" ]]; then
  echo "--only-np must be one of: 2,4,8" >&2
  exit 1
fi
if ! [[ "${size_bytes}" =~ ^[0-9]+$ ]] || [[ "${size_bytes}" == "0" ]]; then
  echo "--size-bytes must be a positive integer" >&2
  exit 1
fi
if ! [[ "${warmup}" =~ ^[0-9]+$ ]]; then
  echo "--warmup must be a non-negative integer" >&2
  exit 1
fi
if ! [[ "${iters}" =~ ^[0-9]+$ ]] || [[ "${iters}" == "0" ]]; then
  echo "--iters must be a positive integer" >&2
  exit 1
fi
if [[ -n "${jct_mode}" && "${jct_mode}" != "safe" && "${jct_mode}" != "performance" ]]; then
  echo "--jct-mode must be safe or performance" >&2
  exit 1
fi
if [[ -n "${inflight_per_peer}" ]] && { ! [[ "${inflight_per_peer}" =~ ^[0-9]+$ ]] || [[ "${inflight_per_peer}" == "0" ]]; }; then
  echo "--inflight-per-peer must be a positive integer" >&2
  exit 1
fi
if [[ -n "${signal_interval}" ]] && { ! [[ "${signal_interval}" =~ ^[0-9]+$ ]] || [[ "${signal_interval}" == "0" ]]; }; then
  echo "--signal-interval must be a positive integer" >&2
  exit 1
fi
if [[ -n "${gid_index}" ]] && ! [[ "${gid_index}" =~ ^[0-9]+$ ]]; then
  echo "--gid-index must be a non-negative integer" >&2
  exit 1
fi
if [[ -n "${total_np}" ]] && { ! [[ "${total_np}" =~ ^[0-9]+$ ]] || [[ "${total_np}" == "0" ]]; }; then
  echo "--total-np must be a positive integer" >&2
  exit 1
fi
case "${bind_to}" in
  none|core|package|hwthread)
    ;;
  *)
    echo "--bind-to must be one of: none,core,package,hwthread" >&2
    exit 1
    ;;
esac

parse_group_spec() {
  local spec="$1"
  local name=""
  local np=""
  local map_by="ppr:2:node"
  local dev_map=""
  local rankfile=""
  local field key value

  IFS=';' read -r -a fields <<< "${spec}"
  for field in "${fields[@]}"; do
    [[ -n "${field}" ]] || continue
    if [[ "${field}" != *=* ]]; then
      echo "Invalid --group field: ${field}" >&2
      exit 1
    fi
    key="${field%%=*}"
    value="${field#*=}"
    case "${key}" in
      name) name="${value}" ;;
      np) np="${value}" ;;
      map-by) map_by="${value}" ;;
      dev-map) dev_map="${value}" ;;
      rankfile) rankfile="${value}" ;;
      *)
        echo "Unknown --group key: ${key}" >&2
        exit 1
        ;;
    esac
  done

  [[ -n "${name}" ]] || { echo "--group requires name=..." >&2; exit 1; }
  [[ -n "${np}" ]] || { echo "--group requires np=..." >&2; exit 1; }
  [[ -n "${dev_map}" ]] || { echo "--group requires dev-map=..." >&2; exit 1; }
  if ! [[ "${np}" =~ ^[0-9]+$ ]] || [[ "${np}" == "0" ]]; then
    echo "--group np must be a positive integer: ${spec}" >&2
    exit 1
  fi
  if [[ -n "${rankfile}" && ! -f "${rankfile}" ]]; then
    echo "Missing --group rankfile: ${rankfile}" >&2
    exit 1
  fi

  group_names+=("${name}")
  group_nps+=("${np}")
  group_map_bys+=("${map_by}")
  group_dev_maps+=("${dev_map}")
  group_rankfiles+=("${rankfile}")
}

merge_rankfiles() {
  local merged="$1"
  local offset=0
  local idx rankfile np
  : > "${merged}"
  for idx in "${!group_names[@]}"; do
    rankfile="${group_rankfiles[$idx]}"
    np="${group_nps[$idx]}"
    if [[ -z "${rankfile}" ]]; then
      echo "Grouped mode currently requires rankfile=... for every --group" >&2
      exit 1
    fi
    awk -v offset="${offset}" '
      /^rank[[:space:]]+[0-9]+=/ {
        line = $0
        sub(/^rank[[:space:]]+/, "", line)
        split(line, parts, /[[:space:]]+/, seps)
        split(parts[1], rank_host, "=")
        newrank = rank_host[1] + offset
        printf("rank %d=%s", newrank, rank_host[2])
        for (i = 2; i in parts; i++) {
          printf(" %s", parts[i])
        }
        printf("\n")
        next
      }
      NF == 0 { next }
      { print }
    ' "${rankfile}" >> "${merged}"
    offset=$((offset + np))
  done
}

run_grouped_mode() {
  local -a hosts=()
  local sum_group_nps=0
  local idx group_np slots_per_host
  local host_arg=""
  local merged_rankfile="${outdir}/alltoall_grouped.rankfile"
  local runtime_rankfile="/tmp/alltoall_grouped_${USER:-u}_$$.rankfile"
  local raw_log="${outdir}/alltoall_grouped_raw.log"
  local summary_file="${outdir}/alltoall_grouped_summary.txt"
  local group_nps_csv=""
  local group_dump_csvs=""
  local global_dev_map=""

  IFS=',' read -r -a hosts <<< "${hosts_csv}"
  if (( ${#hosts[@]} == 0 )); then
    echo "--hosts must list at least one host" >&2
    exit 1
  fi
  for group_spec in "${group_specs[@]}"; do
    parse_group_spec "${group_spec}"
  done
  for group_np in "${group_nps[@]}"; do
    sum_group_nps=$((sum_group_nps + group_np))
  done
  if [[ -n "${total_np}" && "${sum_group_nps}" != "${total_np}" ]]; then
    echo "--total-np=${total_np} does not match group total ${sum_group_nps}" >&2
    exit 1
  fi
  if (( sum_group_nps % ${#hosts[@]} != 0 )); then
    echo "Total group ranks ${sum_group_nps} must divide evenly across ${#hosts[@]} hosts" >&2
    exit 1
  fi
  slots_per_host=$((sum_group_nps / ${#hosts[@]}))
  for host in "${hosts[@]}"; do
    if [[ -n "${host_arg}" ]]; then
      host_arg+=","
    fi
    host_arg+="${host}:${slots_per_host}"
  done
  for idx in "${!group_names[@]}"; do
    if [[ -z "${group_rankfiles[$idx]}" ]]; then
      echo "Grouped mode currently requires rankfile=... for every --group" >&2
      exit 1
    fi
    if [[ "${group_map_bys[$idx]}" == rankfile:file=* ]]; then
      :
    elif [[ "${group_map_bys[$idx]}" != "ppr:2:node" ]]; then
      echo "Grouped single-mpirun mode only supports per-group rankfile mapping" >&2
      exit 1
    fi
    if [[ -n "${group_nps_csv}" ]]; then
      group_nps_csv+=","
      group_dump_csvs+="|"
      global_dev_map+=","
    fi
    group_nps_csv+="${group_nps[$idx]}"
    group_dump_csvs+="${outdir}/alltoall_group_${group_names[$idx]}.csv"
    global_dev_map+="${group_dev_maps[$idx]}"
  done

  mkdir -p "${outdir}"
  : > "${raw_log}"
  merge_rankfiles "${merged_rankfile}"
  for idx in "${!group_names[@]}"; do
    printf '[GROUP %s RANKFILE] %s\n' "${group_names[$idx]}" "${group_rankfiles[$idx]}" >> "${raw_log}"
    cat "${group_rankfiles[$idx]}" >> "${raw_log}"
  done
  printf '[MERGED RANKFILE] %s\n' "${merged_rankfile}" >> "${raw_log}"
  cat "${merged_rankfile}" >> "${raw_log}"
  cp "${merged_rankfile}" "${runtime_rankfile}"
  printf '\n[RUNTIME RANKFILE] %s\n' "${runtime_rankfile}" >> "${raw_log}"
  cat "${runtime_rankfile}" >> "${raw_log}"

  local binary_path="./build/mpi_verbs_global_alltoall"
  if [[ ${dry_run} -eq 0 ]]; then
    ensure_local_binary \
      "./build/mpi_verbs_global_alltoall" \
      "./src/mpi_verbs_global_alltoall.cpp" \
      "mpicxx -O2 -o ./build/mpi_verbs_global_alltoall ./src/mpi_verbs_global_alltoall.cpp -libverbs -lrdmacm"
  fi
  if [[ ${dry_run} -eq 0 && ${skip_sync} -eq 0 ]]; then
    local remote_bin="/tmp/mpi_verbs_global_alltoall_port8_${USER:-u}_$$"
    sync_binary_to_hosts "${binary_path}" "${remote_bin}" "${hosts[@]}"
    binary_path="${remote_bin}"
  fi

  local -a cmd=(
    mpirun --host "${host_arg}" -np "${sum_group_nps}" --map-by "rankfile:file=${runtime_rankfile}" --bind-to "${bind_to}"
    -x "USE_RDMA_CM=${use_rdma_cm}"
    -x "IB_DEV_MAP=${global_dev_map}"
  )
  if [[ -n "${gid_index}" ]]; then
    cmd+=(-x "GID_INDEX=${gid_index}")
  fi
  cmd+=(
    "${binary_path}"
    --bench jct
    --mode write
    --group-nps "${group_nps_csv}"
    --group-dump-csvs "${group_dump_csvs}"
    --iter-world-barrier
    --dump-fct
    --sizes "${size_bytes}"
    --warmup "${warmup}"
    --iters "${iters}"
  )
  if [[ -n "${jct_mode}" ]]; then
    cmd+=(--jct-mode "${jct_mode}")
  fi
  if [[ -n "${inflight_per_peer}" ]]; then
    cmd+=(--inflight-per-peer "${inflight_per_peer}")
  fi
  if [[ -n "${signal_interval}" ]]; then
    cmd+=(--signal-interval "${signal_interval}")
  fi

  printf '%s\n' '[GROUPED CMD]' >> "${raw_log}"
  printf '%s\n' "${cmd[*]}" >> "${raw_log}"
  : > "${summary_file}"
  printf 'group_count=%d\n' "${#group_names[@]}" >> "${summary_file}"
  printf 'total_np=%d\n' "${sum_group_nps}" >> "${summary_file}"
  printf 'group_nps=%s\n' "${group_nps_csv}" >> "${summary_file}"
  printf 'group_csvs=%s\n' "${group_dump_csvs//|/,}" >> "${summary_file}"
  printf 'host_arg=%s\n' "${host_arg}" >> "${summary_file}"
  printf 'merged_rankfile=%s\n' "${merged_rankfile}" >> "${summary_file}"
  printf 'runtime_rankfile=%s\n' "${runtime_rankfile}" >> "${summary_file}"

  if [[ ${dry_run} -eq 1 ]]; then
    sed -i '/^\[GROUP /! s/^/dry-run /' "${raw_log}"
    exit 0
  fi

  set +e
  "${cmd[@]}" > "${outdir}/alltoall_grouped.log" 2>&1
  local overall_rc=$?
  set -e

  cat "${outdir}/alltoall_grouped.log" >> "${raw_log}" || true
  printf 'overall_rc=%s\n' "${overall_rc}" >> "${summary_file}"
  printf 'grouped_log=%s\n' "${outdir}/alltoall_grouped.log" >> "${summary_file}"

  if [[ "${overall_rc}" != "0" ]]; then
    exit 1
  fi
  return 0
}

if (( ${#group_specs[@]} > 0 )); then
  run_grouped_mode
  exit $?
fi

if [[ ${dry_run} -eq 0 ]]; then
  ensure_local_binary \
    "./build/mpi_verbs_global_alltoall" \
    "./src/mpi_verbs_global_alltoall.cpp" \
    "mpicxx -O2 -o ./build/mpi_verbs_global_alltoall ./src/mpi_verbs_global_alltoall.cpp -libverbs -lrdmacm"
fi

mkdir -p "${outdir}"

mapfile -t all_endpoints < <(awk 'NF>0' "${selected_endpoints}")
if (( ${#all_endpoints[@]} < 8 )); then
  echo "Need at least 8 endpoints in ${selected_endpoints} (got ${#all_endpoints[@]})" >&2
  exit 1
fi
selected8=("${all_endpoints[@]:0:8}")

binary_path="./build/mpi_verbs_global_alltoall"
if [[ ${dry_run} -eq 0 && ${skip_sync} -eq 0 ]]; then
  remote_bin="/tmp/mpi_verbs_global_alltoall_port8_${USER:-u}_$$"
  sync_binary_to_hosts "${binary_path}" "${remote_bin}" "${selected8[@]}"
  binary_path="${remote_bin}"
fi

run_case_cmd() {
  local logfile="$1"
  shift
  local -a cmd=("$@")

  if [[ ${dry_run} -eq 1 ]]; then
    {
      local arg
      for arg in "${cmd[@]}"; do
        printf '%s ' "${arg}"
      done
      printf '\n'
    } > "${logfile}"
  else
    "${cmd[@]}" > "${logfile}" 2>&1
  fi
}

build_case_and_run() {
  local np="$1"
  local logfile="$2"
  local -a subset=("${selected8[@]:0:${np}}")

  declare -A host_counts=()
  declare -A host_dev_csv=()
  local -a host_order=()
  local endpoint host dev gid_val
  local -a endpoint_hosts=()
  local -a endpoint_devs=()
  local -a endpoint_gids=()
  local detected_gid=""
  local mixed_gid=0
  for endpoint in "${subset[@]}"; do
    read -r host dev < <(parse_endpoint "${endpoint}")
    endpoint_hosts+=("${host}")
    endpoint_devs+=("${dev}")
    if [[ -z "${host_counts[${host}]:-}" ]]; then
      host_order+=("${host}")
      host_counts["${host}"]=0
      host_dev_csv["${host}"]=""
    fi
    host_counts["${host}"]=$((host_counts["${host}"] + 1))
    if [[ -z "${host_dev_csv[${host}]}" ]]; then
      host_dev_csv["${host}"]="${dev}"
    else
      host_dev_csv["${host}"]+=",${dev}"
    fi
    if [[ -z "${gid_index}" && ${auto_detect_gid} -eq 1 && ${dry_run} -eq 0 ]]; then
      gid_val="$(detect_gid_index_for_host_dev_v2 "${host}" "${dev}")"
      endpoint_gids+=("${gid_val}")
      if [[ -z "${detected_gid}" ]]; then
        detected_gid="${gid_val}"
      elif [[ "${gid_val}" != "${detected_gid}" ]]; then
        mixed_gid=1
      fi
    fi
  done

  local host_spec=""
  local dev_map=""
  local all_one=1
  local all_two=1
  local count
  for host in "${host_order[@]}"; do
    count="${host_counts[${host}]}"
    if [[ "${count}" != "1" ]]; then
      all_one=0
    fi
    if [[ "${count}" != "2" ]]; then
      all_two=0
    fi

    if [[ -n "${host_spec}" ]]; then
      host_spec+=","
    fi
    if [[ "${count}" == "1" ]]; then
      host_spec+="${host}"
    else
      host_spec+="${host}:${count}"
    fi

    if [[ -n "${dev_map}" ]]; then
      dev_map+="|"
    fi
    dev_map+="${host}:${host_dev_csv[${host}]}"
  done

  local map_by="slot"
  if [[ ${all_one} -eq 1 ]]; then
    map_by="ppr:1:node"
  elif [[ ${all_two} -eq 1 ]]; then
    map_by="ppr:2:node"
  fi

  local effective_gid_index="${gid_index}"
  if [[ -z "${effective_gid_index}" && ${auto_detect_gid} -eq 1 && ${dry_run} -eq 0 && ${mixed_gid} -eq 0 ]]; then
    effective_gid_index="${detected_gid}"
    log_info "Auto-detected unified GID_INDEX=${effective_gid_index} (np=${np})"
  fi

  local -a cmd=()
  local appfile=""
  if [[ -z "${gid_index}" && ${auto_detect_gid} -eq 1 && ${dry_run} -eq 0 && ${mixed_gid} -eq 1 ]]; then
    appfile="$(mktemp "${outdir}/alltoall_np${np}.app.XXXXXX")"
    local i
    for (( i = 0; i < ${#subset[@]}; i++ )); do
      append_mpi_appfile_line \
        "${appfile}" \
        "${endpoint_hosts[$i]}" \
        "${endpoint_gids[$i]}" \
        "${endpoint_devs[$i]}" \
        "${use_rdma_cm}" \
        "${binary_path}" \
        --bench jct --dump-fct --sizes "${size_bytes}" --warmup "${warmup}" --iters "${iters}"
    done
    log_info "Mixed GID detected (np=${np}), using mpirun appfile fallback"
    cmd=(mpirun --bind-to "${bind_to}" --app "${appfile}")
  else
    cmd=(
      mpirun --host "${host_spec}" -np "${np}" --map-by "${map_by}" --bind-to "${bind_to}"
      -x "USE_RDMA_CM=${use_rdma_cm}"
      -x "IB_DEV_MAP_BY_HOST=${dev_map}"
    )
    if [[ -n "${effective_gid_index}" ]]; then
      cmd+=(-x "GID_INDEX=${effective_gid_index}")
    fi
    cmd+=("${binary_path}" --bench jct --dump-fct --sizes "${size_bytes}" --warmup "${warmup}" --iters "${iters}")
  fi
  local effective_jct_mode="${jct_mode}"
  local effective_inflight="${inflight_per_peer}"
  local effective_signal="${signal_interval}"
  if [[ ${np2_fast} -eq 1 && "${np}" == "2" ]]; then
    if [[ -z "${effective_jct_mode}" ]]; then
      effective_jct_mode="performance"
    fi
    if [[ -z "${effective_inflight}" ]]; then
      effective_inflight="16"
    fi
    if [[ -z "${effective_signal}" ]]; then
      effective_signal="16"
    fi
  fi
  if [[ -n "${effective_jct_mode}" ]]; then
    cmd+=(--jct-mode "${effective_jct_mode}")
  fi
  if [[ -n "${effective_inflight}" ]]; then
    cmd+=(--inflight-per-peer "${effective_inflight}")
  fi
  if [[ -n "${effective_signal}" ]]; then
    cmd+=(--signal-interval "${effective_signal}")
  fi
  run_case_cmd "${logfile}" "${cmd[@]}"
  if [[ -n "${appfile}" && -f "${appfile}" ]]; then
    rm -f "${appfile}"
  fi
}

if [[ -z "${only_np}" || "${only_np}" == "2" ]]; then
  build_case_and_run 2 "${outdir}/alltoall_np2.log"
  printf '[INFO] wrote %s\n' "${outdir}/alltoall_np2.log"
fi
if [[ -z "${only_np}" || "${only_np}" == "4" ]]; then
  build_case_and_run 4 "${outdir}/alltoall_np4.log"
  printf '[INFO] wrote %s\n' "${outdir}/alltoall_np4.log"
fi
if [[ -z "${only_np}" || "${only_np}" == "8" ]]; then
  build_case_and_run 8 "${outdir}/alltoall_np8.log"
  printf '[INFO] wrote %s\n' "${outdir}/alltoall_np8.log"
fi
