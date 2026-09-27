#!/usr/bin/env bash
set -euo pipefail

log_info() {
  printf '[INFO] %s\n' "$*"
}

local_short_hostname() {
  hostname -s
}

run_cmd_on_host() {
  local host="$1"
  local cmd="$2"
  local local_host
  local remote_escaped
  local_host="$(local_short_hostname)"
  if [[ "${host}" == "${local_host}" ]]; then
    bash -lc "${cmd}"
  else
    remote_escaped="$(printf '%q' "${cmd}")"
    ssh -o BatchMode=yes "${host}" "bash -lc ${remote_escaped}"
  fi
}

parse_endpoint() {
  local ep="$1"
  local host="${ep%%:*}"
  local dev="${ep#*:}"
  if [[ -z "${host}" || -z "${dev}" || "${host}" == "${dev}" ]]; then
    return 1
  fi
  printf '%s %s\n' "${host}" "${dev}"
}

pick_rocev2_gid_index_from_show_gids() {
  local dev="$1"
  local show_gids_output="$2"
  local idx
  idx="$(
    awk -v dev="${dev}" '
      $1 == dev && $2 == "1" {
        gid_idx = $3
        is_v2 = 0
        is_ipv4 = 0
        for (i = 1; i <= NF; i++) {
          if ($i == "v2") {
            is_v2 = 1
          }
          if ($i ~ /ffff:/) {
            is_ipv4 = 1
          }
        }
        if (is_v2 && is_ipv4) {
          chosen = gid_idx
          found = 1
          next
        }
        if (is_v2 && first_v2 == "") {
          first_v2 = gid_idx
        }
      }
      END {
        if (found == 1) {
          print chosen
        } else if (first_v2 != "") {
          print first_v2
        }
      }
    ' <<< "${show_gids_output}"
  )"
  printf '%s\n' "${idx}" | tr -d '[:space:]'
}

pick_rocev2_ipv4_from_show_gids() {
  local dev="$1"
  local show_gids_output="$2"
  local gid_index="${3:-}"
  awk -v dev="${dev}" -v want_idx="${gid_index}" '
    function is_ipv4(tok) {
      return tok ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/
    }
    $1 == dev && $2 == "1" {
      idx = $3
      if (want_idx != "" && idx != want_idx) next
      is_v2 = 0
      ipv4 = ""
      for (i = 1; i <= NF; i++) {
        if ($i == "v2") is_v2 = 1
        if (is_ipv4($i)) ipv4 = $i
      }
      if (is_v2 && ipv4 != "") {
        print ipv4
        exit
      }
    }
  ' <<< "${show_gids_output}"
}

pick_common_rocev2_gid_index_from_show_gids() {
  local dev_a="$1"
  local show_a="$2"
  local dev_b="$3"
  local show_b="$4"

  local -A score_a=()
  local -A score_b=()
  local idx score

  while read -r idx score; do
    [[ -n "${idx}" ]] || continue
    score_a["${idx}"]="${score}"
  done < <(
    awk -v dev="${dev_a}" '
      $1 == dev && $2 == "1" {
        idx = $3
        is_v2 = 0
        is_ipv4 = 0
        for (i = 1; i <= NF; i++) {
          if ($i == "v2") is_v2 = 1
          if ($i ~ /ffff:/) is_ipv4 = 1
        }
        if (!is_v2) next
        score = is_ipv4 ? 2 : 1
        if (!(idx in best) || score > best[idx]) best[idx] = score
      }
      END {
        for (k in best) print k, best[k]
      }
    ' <<< "${show_a}"
  )

  while read -r idx score; do
    [[ -n "${idx}" ]] || continue
    score_b["${idx}"]="${score}"
  done < <(
    awk -v dev="${dev_b}" '
      $1 == dev && $2 == "1" {
        idx = $3
        is_v2 = 0
        is_ipv4 = 0
        for (i = 1; i <= NF; i++) {
          if ($i == "v2") is_v2 = 1
          if ($i ~ /ffff:/) is_ipv4 = 1
        }
        if (!is_v2) next
        score = is_ipv4 ? 2 : 1
        if (!(idx in best) || score > best[idx]) best[idx] = score
      }
      END {
        for (k in best) print k, best[k]
      }
    ' <<< "${show_b}"
  )

  local best_idx=""
  local best_score=0
  for idx in "${!score_a[@]}"; do
    if [[ -z "${score_b[${idx}]:-}" ]]; then
      continue
    fi
    if (( score_a["${idx}"] < score_b["${idx}"] )); then
      score="${score_a[${idx}]}"
    else
      score="${score_b[${idx}]}"
    fi
    if (( score > best_score )) || { (( score == best_score )) && [[ -n "${best_idx}" ]] && (( idx > best_idx )); }; then
      best_score="${score}"
      best_idx="${idx}"
    fi
  done

  if [[ -n "${best_idx}" ]]; then
    printf '%s\n' "${best_idx}"
    return 0
  fi
  return 1
}

declare -gA PORT8_GID_DETECT_CACHE=()

detect_gid_index_for_host_dev_v2() {
  local host="$1"
  local dev="$2"
  local key="${host}|${dev}"
  if [[ -n "${PORT8_GID_DETECT_CACHE[${key}]:-}" ]]; then
    printf '%s\n' "${PORT8_GID_DETECT_CACHE[${key}]}"
    return 0
  fi

  local show_gids_output idx
  show_gids_output="$(run_cmd_on_host "${host}" "show_gids" 2>/dev/null || true)"
  idx="$(pick_rocev2_gid_index_from_show_gids "${dev}" "${show_gids_output}")"
  if [[ -z "${idx}" ]]; then
    printf '[ERROR] failed to detect RoCE v2 GID index for %s:%s\n' "${host}" "${dev}" >&2
    return 1
  fi
  PORT8_GID_DETECT_CACHE["${key}"]="${idx}"
  printf '%s\n' "${idx}"
}

detect_gid_ipv4_for_host_dev_v2() {
  local host="$1"
  local dev="$2"
  local gid_index="${3:-}"
  local show_gids_output
  show_gids_output="$(run_cmd_on_host "${host}" "show_gids" 2>/dev/null || true)"
  pick_rocev2_ipv4_from_show_gids "${dev}" "${show_gids_output}" "${gid_index}"
}

list_rocev2_gid_indexes_for_host_dev() {
  local host="$1"
  local dev="$2"
  local show_gids_output
  show_gids_output="$(run_cmd_on_host "${host}" "show_gids" 2>/dev/null || true)"
  awk -v dev="${dev}" '
    $1 == dev && $2 == "1" {
      gid_idx = $3
      is_v2 = 0
      for (i = 1; i <= NF; i++) {
        if ($i == "v2") {
          is_v2 = 1
        }
      }
      if (is_v2 && !seen[gid_idx]++) {
        print gid_idx
      }
    }
  ' <<< "${show_gids_output}"
}

detect_gid_index_for_endpoint_v2() {
  local endpoint="$1"
  local host dev
  read -r host dev < <(parse_endpoint "${endpoint}")
  detect_gid_index_for_host_dev_v2 "${host}" "${dev}"
}

detect_common_gid_index_for_two_endpoints_v2() {
  local ep_a="$1"
  local ep_b="$2"
  local host_a dev_a host_b dev_b
  local show_a show_b common_idx
  read -r host_a dev_a < <(parse_endpoint "${ep_a}")
  read -r host_b dev_b < <(parse_endpoint "${ep_b}")
  show_a="$(run_cmd_on_host "${host_a}" "show_gids" 2>/dev/null || true)"
  show_b="$(run_cmd_on_host "${host_b}" "show_gids" 2>/dev/null || true)"
  common_idx="$(pick_common_rocev2_gid_index_from_show_gids "${dev_a}" "${show_a}" "${dev_b}" "${show_b}" || true)"
  if [[ -n "${common_idx}" ]]; then
    printf '%s\n' "${common_idx}"
    return 0
  fi
  return 1
}

detect_uniform_gid_index_for_endpoints_v2() {
  local first_idx=""
  local endpoint host dev idx
  local mismatch=""
  for endpoint in "$@"; do
    read -r host dev < <(parse_endpoint "${endpoint}")
    idx="$(detect_gid_index_for_host_dev_v2 "${host}" "${dev}")"
    if [[ -z "${first_idx}" ]]; then
      first_idx="${idx}"
    elif [[ "${idx}" != "${first_idx}" ]]; then
      mismatch+="${host}:${dev}=${idx} "
    fi
  done

  if [[ -n "${mismatch}" ]]; then
    printf '[ERROR] mixed GID index detected; expected unified value=%s but got: %s\n' "${first_idx}" "${mismatch}" >&2
    return 1
  fi
  printf '%s\n' "${first_idx}"
}

append_mpi_appfile_line() {
  local appfile="$1"
  local host="$2"
  local gid_index="$3"
  local dev="$4"
  local use_rdma_cm="$5"
  local binary="$6"
  shift 6

  {
    printf -- '-host %q -np 1 ' "${host}"
    printf -- '-x %q ' "USE_RDMA_CM=${use_rdma_cm}"
    printf -- '-x %q ' "GID_INDEX=${gid_index}"
    printf -- '-x %q ' "IB_DEV_LIST=${dev}"
    printf -- '%q ' "${binary}"
    local arg
    for arg in "$@"; do
      printf -- '%q ' "${arg}"
    done
    printf '\n'
  } >> "${appfile}"
}

build_gid_index_by_host_dev_map_from_endpoints_v2() {
  local endpoint host dev idx host_map
  local -a host_order=()
  declare -A host_seen=()
  declare -A host_dev_map=()
  declare -A host_dev_seen=()

  for endpoint in "$@"; do
    read -r host dev < <(parse_endpoint "${endpoint}")
    if [[ -z "${host_seen[${host}]:-}" ]]; then
      host_seen["${host}"]=1
      host_order+=("${host}")
      host_dev_map["${host}"]=""
    fi
    if [[ -n "${host_dev_seen[${host}|${dev}]:-}" ]]; then
      continue
    fi
    host_dev_seen["${host}|${dev}"]=1
    idx="$(detect_gid_index_for_host_dev_v2 "${host}" "${dev}")"
    if [[ -n "${host_dev_map[${host}]}" ]]; then
      host_dev_map["${host}"]+=","
    fi
    host_dev_map["${host}"]+="${dev}=${idx}"
  done

  host_map=""
  for host in "${host_order[@]}"; do
    if [[ -n "${host_map}" ]]; then
      host_map+="|"
    fi
    host_map+="${host}:${host_dev_map[${host}]}"
  done
  printf '%s\n' "${host_map}"
}

extract_avg_gbps() {
  local log_file="$1"
  local line
  line="$(rg '^write,' "${log_file}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    printf ''
    return 0
  fi
  awk -F',' '{print $7}' <<< "${line}"
}

ensure_local_binary() {
  local bin_path="$1"
  local src_path="$2"
  local build_cmd="$3"
  mkdir -p "$(dirname "${bin_path}")"

  if [[ ! -f "${src_path}" ]]; then
    printf '[ERROR] missing binary %s and source %s\n' "${bin_path}" "${src_path}" >&2
    return 1
  fi

  local need_build=0
  if [[ ! -x "${bin_path}" ]]; then
    need_build=1
  elif [[ "${src_path}" -nt "${bin_path}" ]]; then
    need_build=1
  fi
  for dependency in ./src/*.cpp ./src/*.h; do
    if [[ "${dependency}" -nt "${bin_path}" ]]; then
      need_build=1
    fi
  done

  if [[ ${need_build} -eq 1 ]]; then
    log_info "Building binary: ${bin_path}"
    eval "${build_cmd}"
  fi

  if [[ ! -x "${bin_path}" ]]; then
    printf '[ERROR] failed to build executable %s\n' "${bin_path}" >&2
    return 1
  fi
}

sync_binary_to_hosts() {
  local binary_path="$1"
  local remote_bin="$2"
  shift 2

  local local_host
  local host
  local normalized_host
  local -a hosts=()
  declare -A seen=()

  local_host="$(hostname -s)"
  for host in "$@"; do
    normalized_host="${host%%:*}"
    [[ -z "${normalized_host}" ]] && continue
    if [[ -z "${seen[${normalized_host}]:-}" ]]; then
      seen["${normalized_host}"]=1
      hosts+=("${normalized_host}")
    fi
  done

  for host in "${hosts[@]}"; do
    if [[ "${host}" == "${local_host}" ]]; then
      cp -f "${binary_path}" "${remote_bin}"
      chmod +x "${remote_bin}"
      continue
    fi
    log_info "Sync binary to ${host}:${remote_bin}"
    if ! ssh -o BatchMode=yes "${host}" "true" >/dev/null 2>&1; then
      printf '[ERROR] SSH precheck failed for %s (BatchMode)\n' "${host}" >&2
      return 1
    fi
    if ! cat "${binary_path}" | ssh -o BatchMode=yes "${host}" "cat > '${remote_bin}' && chmod +x '${remote_bin}'"; then
      printf '[ERROR] failed to sync binary to %s\n' "${host}" >&2
      return 1
    fi
  done
}
