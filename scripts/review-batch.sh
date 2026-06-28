#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

if [[ $# -lt 1 ]]; then
    echo "Usage: ./scripts/review-batch.sh <EV> [--form D] [--limit N] [--match text] [--path path]" >&2
    exit 1
fi

EVALUATION_ID="$1"
shift

require_evaluation_dir "${EVALUATION_ID}"

FORM_ID=""
LIMIT=""
MATCH=""
PROJECT_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --form)
            FORM_ID="${2:-}"
            shift 2
            ;;
        --limit)
            LIMIT="${2:-}"
            shift 2
            ;;
        --match)
            MATCH="${2:-}"
            shift 2
            ;;
        --path)
            PROJECT_PATH="${2:-}"
            shift 2
            ;;
        *)
            echo "Unrecognized argument: $1" >&2
            exit 1
            ;;
    esac
done

EVALUATION_DIR="${EVALUATIONS_DIR}/${EVALUATION_ID}"
LOG_DIR="${EVALUATION_DIR}/support/review-batches/$(date +%Y%m%d-%H%M%S)"
mkdir -p "${LOG_DIR}"

mapfile -t PROJECTS < <(
    python3 - <<PYEOF
import json
from pathlib import Path

evaluation_dir = Path("${EVALUATION_DIR}")
requested_form = "${FORM_ID}".strip().upper()
match = "${MATCH}"
explicit_path = "${PROJECT_PATH}".strip()

if explicit_path:
    print(Path(explicit_path).resolve())
    raise SystemExit(0)

students_path = evaluation_dir / "students.json"
payload = json.loads(students_path.read_text(encoding="utf-8")) if students_path.exists() else {"forms": []}
forms = payload.get("forms", [])
folders = []
for form in forms:
    if requested_form and form.get("id", "").upper() != requested_form:
        continue
    folders.append(evaluation_dir / form["folder"])

for folder in folders:
    if not folder.exists():
        continue
    for child in sorted(folder.iterdir()):
        if not child.is_dir():
            continue
        if match and match not in child.name:
            continue
        has_psc = any(p.suffix.lower() in {".psc", ".pseint"} for p in child.rglob("*") if p.is_file())
        if has_psc:
            print(child.resolve())
PYEOF
)

if [[ ${#PROJECTS[@]} -eq 0 ]]; then
    echo "No projects found to review."
    exit 0
fi

if [[ -n "${LIMIT}" ]]; then
    PROJECTS=("${PROJECTS[@]:0:${LIMIT}}")
fi

ok_count=0
fail_count=0

for project in "${PROJECTS[@]}"; do
    label="$(basename "${project}")"
    log_file="${LOG_DIR}/${label}.log"
    echo "=== Reviewing ${project#${WORKSPACE_ROOT}/} ==="
    if "${ENGINE_SCRIPTS_DIR}/review-student.sh" "${project}" | tee "${log_file}"; then
        ok_count=$((ok_count + 1))
    else
        fail_count=$((fail_count + 1))
    fi
done

echo "Review completed: ${ok_count} OK, ${fail_count} with errors."
echo "Logs: ${LOG_DIR#${WORKSPACE_ROOT}/}"
