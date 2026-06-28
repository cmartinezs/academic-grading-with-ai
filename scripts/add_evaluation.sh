#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3
require_course_config

COURSE_CONFIG="${COURSE_DIR}/config.json"
STUDENTS_FILE="${COURSE_DIR}/students.json"

echo ""
echo "=== Create new evaluation ==="
echo ""
read -rp "Evaluation code      (e.g. EV1)                     : " evaluation_id
read -rp "Title                (e.g. Practical execution)     : " evaluation_title
read -rp "Type                 (default: regular)            : " evaluation_type
read -rp "Date                 (YYYY-MM-DD)                   : " evaluation_date
read -rp "Weight               (e.g. 30)                      : " evaluation_weight
read -rp "Forms                (e.g. D,E,F or A,B,C,D)       : " evaluation_forms
echo ""

evaluation_type="${evaluation_type:-regular}"

if [[ -z "${evaluation_id}" || -z "${evaluation_title}" || -z "${evaluation_date}" || -z "${evaluation_weight}" || -z "${evaluation_forms}" ]]; then
    echo "Error: code, title, date, weight, and forms are required." >&2
    exit 1
fi

EVALUATION_DIR="${EVALUATIONS_DIR}/${evaluation_id}"
if [[ -d "${EVALUATION_DIR}" ]]; then
    echo "Warning: ${EVALUATION_DIR} already exists."
    read -rp "Continue without overwriting existing files? (y/N): " confirm
    [[ "${confirm,,}" != "y" ]] && echo "Cancelled." && exit 0
fi

python3 "${ENGINE_SCRIPTS_DIR}/prepare_evaluation.py" \
    --course-config "${COURSE_CONFIG}" \
    --course-students "${STUDENTS_FILE}" \
    --evaluation-dir "${EVALUATION_DIR}" \
    --evaluation-id "${evaluation_id}" \
    --title "${evaluation_title}" \
    --type "${evaluation_type}" \
    --date "${evaluation_date}" \
    --weight "${evaluation_weight}" \
    --forms "${evaluation_forms}" \
    --refresh-plan >/dev/null
python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null

echo "Evaluation registered: ${evaluation_id}"
echo "  - Config updated in evaluations/${SECTION_CODE}/config.json"
echo "  - Structure created in evaluations/${SECTION_CODE}/${evaluation_id}/"
