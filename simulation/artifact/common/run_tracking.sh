#!/usr/bin/env bash

ARTIFACT_STATUS_TOOL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_status.py"
ARTIFACT_MANIFEST_TOOL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_manifest.py"
ARTIFACT_TRACKING_ACTIVE=0
ARTIFACT_TASK_PIDS=()

artifact_tracking_enabled() {
    [[ -n "${ARTIFACT_RUN_DIR:-}" ]]
}

artifact_tracking_init() {
    local section="$1" workload="$2" expected="$3"
    artifact_tracking_enabled || return 0

    python3 "$ARTIFACT_STATUS_TOOL" init \
        --run-dir "$ARTIFACT_RUN_DIR" \
        --section "$section" \
        --workload "$workload" \
        --expected "$expected" || return 1
    export ARTIFACT_HISTORY_FILE="$ARTIFACT_RUN_DIR/history/all.history"
    ARTIFACT_TRACKING_ACTIVE=1
    trap artifact_tracking_on_exit EXIT
}

artifact_result_files_init() {
    local history_file="$1" manifest_file="$2"
    mkdir -p "$(dirname "$history_file")" "$(dirname "$manifest_file")" || return 1
    : > "$history_file" || return 1
    chmod 0644 "$history_file" || return 1
    python3 "$ARTIFACT_MANIFEST_TOOL" init "$manifest_file" || return 1
    export ARTIFACT_HISTORY_FILE="$history_file"
}

artifact_run_command() {
    local manifest_file="$1" task_id="$2" recipe="$3" paper_outputs="$4"
    local topology="$5" workload="$6" group_size="$7" algorithm="$8"
    local timeout_mode="$9" command
    shift 9
    printf -v command '%q ' "$@"
    command=${command% }
    env \
        ARTIFACT_MANIFEST_FILE="$manifest_file" \
        ARTIFACT_TASK_ID="$task_id" \
        ARTIFACT_RECIPE="$recipe" \
        ARTIFACT_PAPER_OUTPUTS="$paper_outputs" \
        ARTIFACT_TOPOLOGY="$topology" \
        ARTIFACT_WORKLOAD="$workload" \
        ARTIFACT_GROUP_SIZE="$group_size" \
        ARTIFACT_ALGORITHM="$algorithm" \
        ARTIFACT_TIMEOUT_MODE="$timeout_mode" \
        ARTIFACT_COMMAND="$command" \
        "$@"
}

artifact_tracking_on_exit() {
    local exit_code=$?
    if ((ARTIFACT_TRACKING_ACTIVE)); then
        python3 "$ARTIFACT_STATUS_TOOL" finalize \
            --run-dir "$ARTIFACT_RUN_DIR" >/dev/null 2>&1 || true
    fi
    return "$exit_code"
}

artifact_update_task() {
    local task_id="$1" status="$2"
    shift 2
    artifact_tracking_enabled || return 0
    python3 "$ARTIFACT_STATUS_TOOL" update \
        --run-dir "$ARTIFACT_RUN_DIR" \
        --task-id "$task_id" \
        --status "$status" \
        "$@"
}

artifact_run_background() {
    local task_id="$1" log_file="$2"
    shift 2

    (
        artifact_update_task "$task_id" running --log "$log_file"
        local exit_code=0 config_id=""
        "$@" > "$log_file" 2>&1 || exit_code=$?

        if artifact_tracking_enabled; then
            config_id=$(sed -n \
                's#.*Config filename:.*/mix/output/\([^/]*\)/config.txt.*#\1#p' \
                "$log_file" | tail -n 1)
            if ((exit_code == 0)) && [[ -n "$config_id" ]]; then
                artifact_update_task "$task_id" completed \
                    --config-id "$config_id" --exit-code 0
            else
                ((exit_code != 0)) || exit_code=1
                if [[ -n "$config_id" ]]; then
                    artifact_update_task "$task_id" failed \
                        --exit-code "$exit_code" --config-id "$config_id"
                else
                    artifact_update_task "$task_id" failed \
                        --exit-code "$exit_code"
                fi
            fi
        fi
        exit "$exit_code"
    ) &
    ARTIFACT_TASK_PIDS+=("$!")
}

artifact_wait_for_tasks() {
    local pid failures=0
    for pid in "${ARTIFACT_TASK_PIDS[@]}"; do
        wait "$pid" || failures=$((failures + 1))
    done
    return "$failures"
}

artifact_tracking_finalize() {
    artifact_tracking_enabled || return 0
    local exit_code=0
    python3 "$ARTIFACT_STATUS_TOOL" finalize \
        --run-dir "$ARTIFACT_RUN_DIR" || exit_code=$?
    ARTIFACT_TRACKING_ACTIVE=0
    return "$exit_code"
}
