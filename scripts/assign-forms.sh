#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3
require_course_config

if [[ $# -lt 1 ]]; then
    echo "Usage: ./scripts/assign-forms.sh <EV> --csv path.csv [--refresh-plan] [--dry-run]" >&2
    exit 1
fi

EVALUATION_ID="$1"
shift

CSV_PATH=""
REFRESH_PLAN="false"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --csv)
            CSV_PATH="${2:-}"
            shift 2
            ;;
        --refresh-plan)
            REFRESH_PLAN="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        *)
            echo "Unrecognized argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "${CSV_PATH}" ]]; then
    echo "Error: you must provide --csv path.csv" >&2
    exit 1
fi

if [[ ! -f "${CSV_PATH}" ]]; then
    echo "Error: the specified CSV does not exist: ${CSV_PATH}" >&2
    exit 1
fi

require_evaluation_dir "${EVALUATION_ID}"

EVALUATION_STUDENTS="${EVALUATIONS_DIR}/${EVALUATION_ID}/students.json"
if [[ ! -f "${EVALUATION_STUDENTS}" ]]; then
    echo "Error: missing ${EVALUATION_STUDENTS}. Run ./scripts/add_evaluation.sh or ./scripts/prepare-evaluation.sh ${EVALUATION_ID} first." >&2
    exit 1
fi

CMD=(
    python3 "${ENGINE_SCRIPTS_DIR}/assign_forms.py"
    --csv "${CSV_PATH}"
    --students "${EVALUATION_STUDENTS}"
    --course-students "${COURSE_DIR}/students.json"
)

[[ "${DRY_RUN}" == "true" ]] && CMD+=(--dry-run)

"${CMD[@]}"

if [[ "${DRY_RUN}" != "true" && "${REFRESH_PLAN}" == "true" ]]; then
    "${SCRIPTS_DIR}/prepare-evaluation.sh" "${EVALUATION_ID}" --refresh-plan >/dev/null
    echo "Plan synced: evaluations/${SECTION_CODE}/${EVALUATION_ID}/plan.md"
else
    python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null
fi
