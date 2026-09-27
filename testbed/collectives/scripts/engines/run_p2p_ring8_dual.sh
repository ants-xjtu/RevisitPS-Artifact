#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

source scripts/engines/lib/common.sh

hosts_csv=""
outdir=""
total_np=""
size_token="160M"
warmup=20
iters=500
inflight=1
sig_interval=1
write_chunk="1M"
write_notify="none"
bench_mode="latency"
latency_metric="fct"
gid_index="${GID_INDEX:-3}"
bind_to="core"
dry_run=0
skip_sync=0
binary_path="./build/mpi_verbs_p2p_ring4"
dev_map_a="mlx5_0,mlx5_2,mlx5_0,mlx5_2,mlx5_0,mlx5_2,mlx5_0,mlx5_2"
dev_map_b="mlx5_1,mlx5_3,mlx5_1,mlx5_3,mlx5_1,mlx5_3,mlx5_1,mlx5_3"
ring_order_a=""
ring_order_b=""
rankfile_a=""
rankfile_b=""
dump_iter_fct_a=""
dump_iter_fct_b=""
declare -a group_specs=()
declare -a group_names=()
declare -a group_nps=()
declare -a group_map_bys=()
declare -a group_dev_maps=()
declare -a group_ring_orders=()
declare -a group_rankfiles=()
declare -a group_dump_iter_fcts=()

usage() {
  cat <<'EOF' >&2
Usage: run_p2p_ring8_dual.sh --hosts dc20,dc21,dc22,dc23 --outdir DIR [options]
  --total-np N                Expected total ranks across all groups
  --group SPEC                Group spec: name=G;np=8;map-by=ppr:2:node;dev-map=...;ring-order=...;rankfile=...;dump-iter-fct=...
  --size SIZE                 Message size token, default 160M
  --warmup N                  Warmup iterations, default 20
  --iters N                   Measured iterations, default 500
  --inflight N                Inflight depth, default 1
  --sig-interval N            Signaled interval, default 1
  --write-chunk SIZE          RDMA write chunk size, default 1M
  --write-notify imm|none     Write notify mode, default none
  --bench bw|latency          Benchmark mode, default latency
  --latency-metric rtt2|fct   Latency metric, default fct
  --gid-index N               GID index, default \$GID_INDEX or 3
  --bind-to MODE              Open MPI bind policy, default core
  --binary PATH               Local binary path, default ./build/mpi_verbs_p2p_ring4
  --dev-map-a CSV             8-rank IB_DEV_MAP for group A
  --dev-map-b CSV             8-rank IB_DEV_MAP for group B
  --ring-order-a CSV          Custom ring order for group A
  --ring-order-b CSV          Custom ring order for group B
  --rankfile-a PATH           Custom rankfile for group A
  --rankfile-b PATH           Custom rankfile for group B
  --dump-iter-fct-a PATH      Per-iteration FCT dump path for group A
  --dump-iter-fct-b PATH      Per-iteration FCT dump path for group B
  --skip-sync                 Do not copy the binary to remote hosts
  --dry-run                   Only emit commands
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --size)
      size_token="$2"
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
    --inflight)
      inflight="$2"
      shift 2
      ;;
    --sig-interval)
      sig_interval="$2"
      shift 2
      ;;
    --write-chunk)
      write_chunk="$2"
      shift 2
      ;;
    --write-notify)
      write_notify="$2"
      shift 2
      ;;
    --bench)
      bench_mode="$2"
      shift 2
      ;;
    --latency-metric)
      latency_metric="$2"
      shift 2
      ;;
    --gid-index)
      gid_index="$2"
      shift 2
      ;;
    --bind-to)
      bind_to="$2"
      shift 2
      ;;
    --binary)
      binary_path="$2"
      shift 2
      ;;
    --dev-map-a)
      dev_map_a="$2"
      shift 2
      ;;
    --dev-map-b)
      dev_map_b="$2"
      shift 2
      ;;
    --ring-order-a)
      ring_order_a="$2"
      shift 2
      ;;
    --ring-order-b)
      ring_order_b="$2"
      shift 2
      ;;
    --rankfile-a)
      rankfile_a="$2"
      shift 2
      ;;
    --rankfile-b)
      rankfile_b="$2"
      shift 2
      ;;
    --dump-iter-fct-a)
      dump_iter_fct_a="$2"
      shift 2
      ;;
    --dump-iter-fct-b)
      dump_iter_fct_b="$2"
      shift 2
      ;;
    --skip-sync)
      skip_sync=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    *)
      printf 'Unknown arg: %s\n' "$1" >&2
      usage
      ;;
  esac
done

[[ -n "${hosts_csv}" ]] || usage
[[ -n "${outdir}" ]] || usage

parse_group_spec() {
  local spec="$1"
  local name=""
  local np=""
  local map_by="ppr:2:node"
  local dev_map=""
  local ring_order=""
  local rankfile=""
  local dump_iter_fct=""
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
      name)
        name="${value}"
        ;;
      np)
        np="${value}"
        ;;
      map-by)
        map_by="${value}"
        ;;
      dev-map)
        dev_map="${value}"
        ;;
      ring-order)
        ring_order="${value}"
        ;;
      rankfile)
        rankfile="${value}"
        ;;
      dump-iter-fct)
        dump_iter_fct="${value}"
        ;;
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
  group_ring_orders+=("${ring_order}")
  group_rankfiles+=("${rankfile}")
  group_dump_iter_fcts+=("${dump_iter_fct}")
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
      echo "Grouped single-mpirun mode requires rankfile=... for every group" >&2
      exit 1
    fi
    awk -v offset="${offset}" '
      /^[[:space:]]*$/ { next }
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
      { print }
    ' "${rankfile}" >> "${merged}"
    offset=$((offset + np))
  done
}

if ! [[ "${warmup}" =~ ^[0-9]+$ ]]; then
  echo "--warmup must be a non-negative integer" >&2
  exit 1
fi
if ! [[ "${iters}" =~ ^[0-9]+$ ]] || [[ "${iters}" == "0" ]]; then
  echo "--iters must be a positive integer" >&2
  exit 1
fi
if ! [[ "${inflight}" =~ ^[0-9]+$ ]] || [[ "${inflight}" == "0" ]]; then
  echo "--inflight must be a positive integer" >&2
  exit 1
fi
if ! [[ "${sig_interval}" =~ ^[0-9]+$ ]] || [[ "${sig_interval}" == "0" ]]; then
  echo "--sig-interval must be a positive integer" >&2
  exit 1
fi
if [[ "${bench_mode}" != "bw" && "${bench_mode}" != "latency" ]]; then
  echo "--bench must be one of: bw,latency" >&2
  exit 1
fi
if [[ "${latency_metric}" != "rtt2" && "${latency_metric}" != "fct" ]]; then
  echo "--latency-metric must be one of: rtt2,fct" >&2
  exit 1
fi
if [[ "${write_notify}" != "imm" && "${write_notify}" != "none" ]]; then
  echo "--write-notify must be imm or none" >&2
  exit 1
fi
if [[ "${bind_to}" != "none" && "${bind_to}" != "core" && "${bind_to}" != "package" && "${bind_to}" != "hwthread" ]]; then
  echo "--bind-to must be one of: none,core,package,hwthread" >&2
  exit 1
fi
if [[ -n "${rankfile_a}" && ! -f "${rankfile_a}" ]]; then
  echo "Missing --rankfile-a: ${rankfile_a}" >&2
  exit 1
fi
if [[ -n "${rankfile_b}" && ! -f "${rankfile_b}" ]]; then
  echo "Missing --rankfile-b: ${rankfile_b}" >&2
  exit 1
fi
if [[ -n "${total_np}" ]] && { ! [[ "${total_np}" =~ ^[0-9]+$ ]] || [[ "${total_np}" == "0" ]]; }; then
  echo "--total-np must be a positive integer" >&2
  exit 1
fi
if [[ "${bench_mode}" == "latency" && "${inflight}" != "1" ]]; then
  echo "Latency benchmark requires --inflight 1" >&2
  exit 1
fi

IFS=',' read -r -a hosts <<< "${hosts_csv}"
if (( ${#hosts[@]} == 0 )); then
  echo "--hosts must list at least one host" >&2
  exit 1
fi

if (( ${#group_specs[@]} > 0 )); then
  for group_spec in "${group_specs[@]}"; do
    parse_group_spec "${group_spec}"
  done
else
  group_names=("A" "B")
  group_nps=("8" "8")
  group_map_bys=("ppr:2:node" "ppr:2:node")
  group_dev_maps=("${dev_map_a}" "${dev_map_b}")
  group_ring_orders=("${ring_order_a}" "${ring_order_b}")
  group_rankfiles=("${rankfile_a}" "${rankfile_b}")
  group_dump_iter_fcts=("${dump_iter_fct_a}" "${dump_iter_fct_b}")
fi

sum_group_nps=0
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
host_arg=""
for host in "${hosts[@]}"; do
  if [[ -n "${host_arg}" ]]; then
    host_arg+=","
  fi
  host_arg+="${host}:${slots_per_host}"
done

mkdir -p "${outdir}"
raw_log="${outdir}/p2p_ring8_dual_raw.log"
summary_file="${outdir}/ring8_dual_summary.txt"
merged_rankfile="${outdir}/ring8_dual_merged.rankfile"
runtime_rankfile="/tmp/ring8dual_${USER:-u}_$$.rankfile"
: > "${raw_log}"

if [[ ${dry_run} -eq 0 ]]; then
  ensure_local_binary \
    "${binary_path}" \
    "./src/mpi_verbs_p2p_ring4.cpp" \
    "mpicxx -O2 -o ${binary_path} ./src/mpi_verbs_p2p_ring4.cpp -libverbs -lrdmacm"
fi

remote_bin="${binary_path}"
if [[ ${dry_run} -eq 0 && ${skip_sync} -eq 0 ]]; then
  remote_bin="/tmp/mpi_verbs_p2p_ring4_${USER:-u}_$$"
  sync_binary_to_hosts "${binary_path}" "${remote_bin}" "${hosts[@]}"
fi

group_nps_csv=""
group_ring_orders_spec=""
group_dump_iter_fct_spec=""
global_dev_map=""

for idx in "${!group_names[@]}"; do
  if [[ -z "${group_rankfiles[$idx]}" ]]; then
    echo "Grouped single-mpirun mode requires rankfile=... for every group" >&2
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
    group_ring_orders_spec+="|"
    group_dump_iter_fct_spec+="|"
    global_dev_map+=","
  fi
  group_nps_csv+="${group_nps[$idx]}"
  group_ring_orders_spec+="${group_ring_orders[$idx]}"
  group_dump_iter_fct_spec+="${group_dump_iter_fcts[$idx]}"
  global_dev_map+="${group_dev_maps[$idx]}"
  printf '[GROUP %s RANKFILE] %s\n' "${group_names[$idx]}" "${group_rankfiles[$idx]}" >> "${raw_log}"
  cat "${group_rankfiles[$idx]}" >> "${raw_log}"
done

merge_rankfiles "${merged_rankfile}"
printf '[MERGED RANKFILE] %s\n' "${merged_rankfile}" >> "${raw_log}"
cat "${merged_rankfile}" >> "${raw_log}"
cp "${merged_rankfile}" "${runtime_rankfile}"
printf '\n[RUNTIME RANKFILE] %s\n' "${runtime_rankfile}" >> "${raw_log}"
cat "${runtime_rankfile}" >> "${raw_log}"

declare -a cmd=(
  mpirun --host "${host_arg}" -np "${sum_group_nps}" --map-by "rankfile:file=${runtime_rankfile}" --bind-to "${bind_to}"
  -x "IB_DEV_MAP=${global_dev_map}"
  -x "GID_INDEX=${gid_index}"
  "${remote_bin}"
  --bench "${bench_mode}"
  --mode write
  --sizes "${size_token}"
  --warmup "${warmup}"
  --iters "${iters}"
  --inflight "${inflight}"
  --sig-interval "${sig_interval}"
  --write-notify "${write_notify}"
  --latency-metric "${latency_metric}"
  --group-nps "${group_nps_csv}"
  --iter-barrier
)
if [[ -n "${write_chunk}" ]]; then
  cmd+=(--write-chunk "${write_chunk}")
fi
if [[ -n "${group_ring_orders_spec//|/}" ]]; then
  cmd+=(--group-ring-orders "${group_ring_orders_spec}")
fi
if [[ -n "${group_dump_iter_fct_spec//|/}" ]]; then
  cmd+=(--group-dump-iter-fct "${group_dump_iter_fct_spec}")
fi

printf '%s\n' '[GROUPED CMD]' >> "${raw_log}"
printf '%s\n' "${cmd[*]}" >> "${raw_log}"

: > "${summary_file}"
printf 'group_count=%d\n' "${#group_names[@]}" >> "${summary_file}"
printf 'total_np=%d\n' "${sum_group_nps}" >> "${summary_file}"
printf 'group_nps=%s\n' "${group_nps_csv}" >> "${summary_file}"
printf 'host_arg=%s\n' "${host_arg}" >> "${summary_file}"
printf 'merged_rankfile=%s\n' "${merged_rankfile}" >> "${summary_file}"
printf 'runtime_rankfile=%s\n' "${runtime_rankfile}" >> "${summary_file}"

if [[ ${dry_run} -eq 1 ]]; then
  sed -i '/^\[GROUP /! s/^/dry-run /' "${raw_log}"
  exit 0
fi

set +e
"${cmd[@]}" > "${outdir}/ring_grouped.log" 2>&1
overall_rc=$?
set -e

cat "${outdir}/ring_grouped.log" >> "${raw_log}" || true
printf 'overall_rc=%s\n' "${overall_rc}" >> "${summary_file}"
printf 'grouped_log=%s\n' "${outdir}/ring_grouped.log" >> "${summary_file}"

if [[ "${overall_rc}" != "0" ]]; then
  exit 1
fi
