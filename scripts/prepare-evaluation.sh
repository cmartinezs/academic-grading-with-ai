#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3
require_course_config

if [[ $# -lt 1 ]]; then
    echo "Usage: ./scripts/prepare-evaluation.sh <EV> [--forms D,E,F] [--title ...] [--type ...] [--date YYYY-MM-DD] [--weight 30] [--refresh-plan]" >&2
    exit 1
fi

EVALUATION_ID="$1"
shift

FORMS=""
TITLE=""
TYPE=""
DATE=""
WEIGHT=""
REFRESH_PLAN="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --forms)
            FORMS="${2:-}"
            shift 2
            ;;
        --title)
            TITLE="${2:-}"
            shift 2
            ;;
        --type)
            TYPE="${2:-}"
            shift 2
            ;;
        --date)
            DATE="${2:-}"
            shift 2
            ;;
        --weight)
            WEIGHT="${2:-}"
            shift 2
            ;;
        --refresh-plan)
            REFRESH_PLAN="true"
            shift
            ;;
        *)
            echo "Unrecognized argument: $1" >&2
            exit 1
            ;;
    esac
done

EVALUATION_DIR="${EVALUATIONS_DIR}/${EVALUATION_ID}"
mkdir -p "${EVALUATION_DIR}"

CMD=(
    python3 "${ENGINE_SCRIPTS_DIR}/prepare_evaluation.py"
    --course-config "${COURSE_DIR}/config.json"
    --course-students "${COURSE_DIR}/students.json"
    --evaluation-dir "${EVALUATION_DIR}"
    --evaluation-id "${EVALUATION_ID}"
)

[[ -n "${FORMS}" ]] && CMD+=(--forms "${FORMS}")
[[ -n "${TITLE}" ]] && CMD+=(--title "${TITLE}")
[[ -n "${TYPE}" ]] && CMD+=(--type "${TYPE}")
[[ -n "${DATE}" ]] && CMD+=(--date "${DATE}")
[[ -n "${WEIGHT}" ]] && CMD+=(--weight "${WEIGHT}")
[[ "${REFRESH_PLAN}" == "true" ]] && CMD+=(--refresh-plan)

"${CMD[@]}" >/dev/null
python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null

echo "Evaluation synced: ${EVALUATION_ID}"
echo "  - EV roster: evaluations/${SECTION_CODE}/${EVALUATION_ID}/students.json"
if [[ "${REFRESH_PLAN}" == "true" ]]; then
    echo "  - plan regenerated: evaluations/${SECTION_CODE}/${EVALUATION_ID}/plan.md"
fi
