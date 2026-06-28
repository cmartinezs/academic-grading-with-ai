#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3
require_course_config

CSV_PATH=""
FORCE="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --csv)
            CSV_PATH="${2:-}"
            shift 2
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        *)
    echo "Usage: ./scripts/import-students.sh --csv path.csv [--force]" >&2
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

TARGET_FILE="${COURSE_DIR}/students.json"
if [[ -f "${TARGET_FILE}" && "${FORCE}" != "true" ]]; then
    if ! confirm_overwrite "evaluations/${SECTION_CODE}/students.json will be replaced"; then
        echo "Cancelled."
        exit 0
    fi
fi

python3 "${ENGINE_SCRIPTS_DIR}/students_csv_to_json.py" --csv "${CSV_PATH}" --out "${TARGET_FILE}"
python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null

COUNT=$(python3 - <<PYEOF
import json
from pathlib import Path
payload = json.loads(Path("${TARGET_FILE}").read_text(encoding="utf-8"))
print(len(payload.get("students", [])))
PYEOF
)

echo "Roster imported into evaluations/${SECTION_CODE}/students.json (${COUNT} students)."
echo "Next step: sync each EV with ./scripts/prepare-evaluation.sh <EV> [--refresh-plan]"
