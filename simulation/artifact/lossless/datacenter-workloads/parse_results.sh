#!/usr/bin/env bash
set -euo pipefail

# Raw ns-3 logs -> parser JSON for Figures 4--6 and Table 4.
# Parsers with hard-coded output directories are mirrored unchanged into
# results/parser_stage so the repository's parser/ directory remains clean.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS3_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PARSER_DIR="${NS3_ROOT}/parser"
RESULTS="${SCRIPT_DIR}/results"
HISTORY="${RESULTS}/lossless_datacenter.history"
SELECTED="${RESULTS}/selected_history"
JSON_ROOT="${RESULTS}/json"
STAGE="${RESULTS}/parser_stage"
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: ./artifact/lossless/datacenter-workloads/parse_results.sh [--dry-run]

Parsers:
  Figure 4  parser/parse_dcn_fct_rto.py
  Figure 5  parser/parse_dcn_ooo.py
  Figure 6  parser/parse_dcn_pfc_trigger.py
  Table 4   parser/parse_dcn_spine_qlen.py, then build_table4.py
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

print_command() {
    printf 'PARSER_COMMAND'
    printf ' %q' "$@"
    printf '\n'
}

if ((DRY_RUN)); then
    print_command python3 "${PARSER_DIR}/parse_dcn_fct_rto.py" "${SELECTED}/figure4.history" -o "${JSON_ROOT}/figure4"
    print_command python3 "${PARSER_DIR}/parse_dcn_ooo.py" "${SELECTED}/figure5.history"
    print_command python3 "${PARSER_DIR}/parse_dcn_pfc_trigger.py" "${SELECTED}/figure6.history"
    print_command python3 "${PARSER_DIR}/parse_dcn_spine_qlen.py" "${SELECTED}/table4.history" --n_leaf 8 --n_spine 8 --servers_per_leaf 16
    print_command python3 "${SCRIPT_DIR}/build_table4.py" "${JSON_ROOT}/table4/table4.json" "${RESULTS}/tables"
    exit 0
fi

[[ -s "$HISTORY" ]] || die "missing ${HISTORY}; run run_experiments.sh first"
mkdir -p "$SELECTED" "$JSON_ROOT" "$STAGE" "${RESULTS}/tables"

select_rows() {
    local output="$1"
    local expression="$2"
    local expected="$3"
    awk -F, "$expression" "$HISTORY" > "$output"
    local actual
    actual="$(wc -l < "$output")"
    [[ "$actual" -eq "$expected" ]] || die "${output} has ${actual} rows; expected ${expected}"
}

# History fields: $16=topology, $18=workload, $19=load.
select_rows "${SELECTED}/figure4.history" '($16=="leaf_spine_128_100G_OS2" && $18=="AliStorage2019" && $19=="80") || ($16=="fat_k8_100G_OS1" && $18=="AliStorage2019" && $19=="80")' 10
select_rows "${SELECTED}/figure5.history" '$16=="leaf_spine_128_100G_OS2" && $18=="AliStorage2019" && $19=="80"' 5
select_rows "${SELECTED}/figure6.history" '($16=="fat_k8_100G_OS1" && $18=="Solar2022" && $19=="80") || ($16=="leaf_spine_128_100G_OS2" && $18=="AliStorage2019" && $19=="80") || ($16=="leaf_spine_L8_S16_100G_OS1" && $18=="FbHdp2015" && $19=="80")' 15
cp "${SELECTED}/figure5.history" "${SELECTED}/table4.history"

stage_parser() {
    local stage_name="$1"
    local parser_name="$2"
    shift 2
    local stage_root="${STAGE}/${stage_name}"
    mkdir -p "${stage_root}/parser"
    cp "${PARSER_DIR}/${parser_name}" "${stage_root}/parser/${parser_name}"
    ln -sfn "${NS3_ROOT}/mix" "${stage_root}/mix"
    ln -sfn "${NS3_ROOT}/config" "${stage_root}/config"
    ln -sfn "${NS3_ROOT}/analysis" "${stage_root}/analysis"
    python3 "${stage_root}/parser/${parser_name}" "$@"
}

# Figure 4 JSON: parse FCT logs for scenarios A and B.
mkdir -p "${JSON_ROOT}/figure4"
python3 "${PARSER_DIR}/parse_dcn_fct_rto.py" "${SELECTED}/figure4.history" -o "${JSON_ROOT}/figure4"

# Figure 5 JSON: parse OOO/drop logs for scenario A.
stage_parser figure5 parse_dcn_ooo.py "${SELECTED}/figure5.history"
figure5_source="${STAGE}/figure5/parser/json-data-ooo-asy/OOO_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"
[[ -s "$figure5_source" ]] || die "Figure 5 parser did not produce ${figure5_source}"
mkdir -p "${JSON_ROOT}/figure5"
cp "$figure5_source" "${JSON_ROOT}/figure5/figure5.json"

# Figure 6 JSON: parse PFC logs for scenarios C, A, and D.
stage_parser figure6 parse_dcn_pfc_trigger.py "${SELECTED}/figure6.history"
figure6_source="${STAGE}/figure6/parser/json-data-pfc"
shopt -s nullglob
figure6_files=("${figure6_source}"/PFC_DATA_*.json)
shopt -u nullglob
(("${#figure6_files[@]}" == 3)) || die "Figure 6 parser produced ${#figure6_files[@]} JSON files; expected 3"
mkdir -p "${JSON_ROOT}/figure6"
cp "${figure6_files[@]}" "${JSON_ROOT}/figure6/"

# Table 4 JSON: parse spine egress queues for scenario A.
stage_parser table4 parse_dcn_spine_qlen.py "${SELECTED}/table4.history" --n_leaf 8 --n_spine 8 --servers_per_leaf 16
table4_source="${STAGE}/table4/parser/json-data-spine-qlen/QLEN_DATA_TOPO_leaf_spine_128_100G_OS2_LOAD_80_FC_Lossless_TYPE_AliStorage2019_ERR_0.0.json"
[[ -s "$table4_source" ]] || die "Table 4 parser did not produce ${table4_source}"
mkdir -p "${JSON_ROOT}/table4"
cp "$table4_source" "${JSON_ROOT}/table4/table4.json"
python3 "${SCRIPT_DIR}/build_table4.py" "${JSON_ROOT}/table4/table4.json" "${RESULTS}/tables"

echo "Parser JSON written below ${JSON_ROOT}"
echo "Table 4 written below ${RESULTS}/tables"
echo "Next: ${SCRIPT_DIR}/plot_results.sh"
