#!/usr/bin/env bash

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECTION_CODE="${SECTION_CODE:-}"
SECTION_DIR=""
COURSE_DIR=""
EVALUATIONS_DIR=""
SCRIPTS_DIR="${WORKSPACE_ROOT}/scripts"
ENGINE_SCRIPTS_DIR="${WORKSPACE_ROOT}/engine/scripts"

refresh_section_paths() {
    if [[ -n "${SECTION_CODE}" ]]; then
        SECTION_DIR="${WORKSPACE_ROOT}/evaluations/${SECTION_CODE}"
        COURSE_DIR="${SECTION_DIR}"
        EVALUATIONS_DIR="${SECTION_DIR}"
    else
        SECTION_DIR=""
        COURSE_DIR=""
        EVALUATIONS_DIR=""
    fi
}

resolve_section_code() {
    if [[ -n "${SECTION_CODE}" ]]; then
        refresh_section_paths
        return 0
    fi

    local section_dirs=()
    local dir
    if [[ -d "${WORKSPACE_ROOT}/evaluations" ]]; then
        while IFS= read -r -d '' dir; do
            [[ -f "${dir}/config.json" ]] && section_dirs+=("${dir##*/}")
        done < <(find "${WORKSPACE_ROOT}/evaluations" -mindepth 1 -maxdepth 1 -type d -print0)
    fi

    if [[ ${#section_dirs[@]} -eq 1 ]]; then
        SECTION_CODE="${section_dirs[0]}"
        export SECTION_CODE
        refresh_section_paths
        return 0
    fi

    if [[ ${#section_dirs[@]} -eq 0 ]]; then
        echo "Error: no active section was found. Define SECTION_CODE or initialize a section." >&2
        exit 1
    fi

    echo "Error: more than one section exists in evaluations/. Define SECTION_CODE before running this script." >&2
    exit 1
}

require_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "Error: required command not available: $1" >&2
        exit 1
    fi
}

require_course_config() {
    resolve_section_code
    if [[ ! -f "${COURSE_DIR}/config.json" ]]; then
        echo "Error: missing evaluations/${SECTION_CODE}/config.json. Run ./scripts/init-course.sh first." >&2
        exit 1
    fi
}

require_evaluation_dir() {
    local evaluation_id="$1"
    resolve_section_code
    if [[ ! -d "${EVALUATIONS_DIR}/${evaluation_id}" ]]; then
        echo "Error: evaluations/${SECTION_CODE}/${evaluation_id} does not exist." >&2
        exit 1
    fi
}

confirm_overwrite() {
    local message="$1"
    read -rp "${message} (y/N): " confirm
    [[ "${confirm,,}" == "y" ]]
}
