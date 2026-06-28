#!/usr/bin/env bash
# Bootstraps the active section handled by this workspace.
# Use --replace-root to overwrite evaluations/<section_code>/.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

MODE="init"
STUDENTS_CSV_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --replace-root)
            MODE="replace-root"
            shift
            ;;
        --students-csv)
            STUDENTS_CSV_PATH="${2:-}"
            if [[ -z "${STUDENTS_CSV_PATH}" ]]; then
                echo "Error: --students-csv requires a path." >&2
                exit 1
            fi
            shift 2
            ;;
        *)
            echo "Error: unrecognized argument: $1" >&2
            echo "Usage: ./scripts/init-course.sh [--replace-root] [--students-csv path.csv]" >&2
            exit 1
            ;;
    esac
done

require_command python3

echo ""
echo "=== New course initialization ==="
echo ""
read -rp  "Course code           (e.g. CUR0001)             : " course_code
read -rp  "Title                 (e.g. Sample course)       : " course_title
read -rp  "Section               (e.g. 001)                 : " section
read -rp  "Term                  (e.g. 2026)                : " term

if [[ -z "${STUDENTS_CSV_PATH}" ]]; then
    echo ""
    read -rp "Student CSV path (optional)                       : " STUDENTS_CSV_PATH
fi

echo ""

course_name="${course_code}-${section}"
TARGET_CONFIG_DIR="${WORKSPACE_ROOT}/evaluations/${course_name}"
TARGET_EVALUATIONS_DIR="${TARGET_CONFIG_DIR}"
TARGET_LABEL="evaluations/${course_name}/"

if [[ -f "${TARGET_CONFIG_DIR}/config.json" ]]; then
    echo ""
    if [[ "${MODE}" != "replace-root" ]]; then
        echo "Warning: evaluations/${course_name}/config.json already exists."
        echo "Use ./scripts/init-course.sh --replace-root to replace it."
        exit 1
    fi
    echo "Warning: the current section at evaluations/${course_name}/ will be overwritten."
    read -rp "Continue? (y/N): " confirm
    [[ "${confirm,,}" != "y" ]] && echo "Cancelled." && exit 0
fi

if [[ -n "${STUDENTS_CSV_PATH}" && ! -f "${STUDENTS_CSV_PATH}" ]]; then
    echo "Error: the specified CSV does not exist: ${STUDENTS_CSV_PATH}" >&2
    exit 1
fi

mkdir -p "${TARGET_CONFIG_DIR}" "${TARGET_EVALUATIONS_DIR}"

COURSE_NAME="$course_name" COURSE_TITLE="$course_title" SECTION="$section" TERM="$term" CONFIG_OUT="${TARGET_CONFIG_DIR}/config.json" python3 - << 'PYEOF'
import json
import os
from pathlib import Path

config = {
    "course": {
        "name": os.environ["COURSE_NAME"],
        "title": os.environ["COURSE_TITLE"],
        "section": os.environ["SECTION"],
        "term": os.environ["TERM"],
    },
    "evaluations": {},
}

Path(os.environ["CONFIG_OUT"]).write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PYEOF

if [[ -n "${STUDENTS_CSV_PATH}" ]]; then
    python3 "${ENGINE_SCRIPTS_DIR}/students_csv_to_json.py" --csv "${STUDENTS_CSV_PATH}" --out "${TARGET_CONFIG_DIR}/students.json"
else
    python3 - <<PYEOF
import json
from pathlib import Path

Path("${TARGET_CONFIG_DIR}/students.json").write_text(
    json.dumps({"students": []}, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PYEOF
fi

SECTION_CODE="${course_name}" python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${course_name}" >/dev/null

echo ""
echo "Course initialized: ${course_name} — ${course_title} (${term})"
echo ""
echo "  ${TARGET_LABEL}config.json                 generated"
echo "  ${TARGET_LABEL}students.json               generated"
echo "  ${TARGET_EVALUATIONS_DIR#${WORKSPACE_ROOT}/}/                 ready"
echo ""
echo "Expected CSV format:"
echo "  order,rut,names,lastName,secondLastName,repoUrl,avaUser,fullName"
echo ""
echo "Next steps:"
echo "  1. Complete or review ${TARGET_LABEL}students.json."
echo "  2. Register evaluations with ./scripts/add_evaluation.sh"
echo "  3. Grade submissions and generate Markdown results per student."
echo "  4. python3 engine/scripts/export-publication-data.py"
