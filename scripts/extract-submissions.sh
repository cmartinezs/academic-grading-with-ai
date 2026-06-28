#!/usr/bin/env bash

set -euo pipefail
shopt -s nullglob dotglob

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

if [[ $# -lt 1 ]]; then
    echo "Usage: ./scripts/extract-submissions.sh <EV> [--form D] [--match text]" >&2
    exit 1
fi

EVALUATION_ID="$1"
shift

FORM_ID=""
MATCH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --form)
            FORM_ID="${2:-}"
            shift 2
            ;;
        --match)
            MATCH="${2:-}"
            shift 2
            ;;
        *)
            echo "Unrecognized argument: $1" >&2
            exit 1
            ;;
    esac
done

require_evaluation_dir "${EVALUATION_ID}"
require_command unzip

EVALUATION_DIR="${EVALUATIONS_DIR}/${EVALUATION_ID}"

FORM_FOLDER=$(python3 - <<PYEOF
import json
from pathlib import Path

students_path = Path("${EVALUATION_DIR}/students.json")
payload = json.loads(students_path.read_text(encoding="utf-8")) if students_path.exists() else {"forms": []}
forms = payload.get("forms", [])
requested = "${FORM_ID}".strip().upper()

if requested:
    for form in forms:
        if form.get("id", "").upper() == requested:
            print(form["folder"])
            break
    else:
        raise SystemExit(f"Error: form {requested} does not exist in {students_path}")
elif len(forms) == 1:
    print(forms[0]["folder"])
else:
    raise SystemExit("Error: you must provide --form when the evaluation has more than one form.")
PYEOF
)

INPUT_DIR="${EVALUATION_DIR}/${FORM_FOLDER}/submissions"
if [[ ! -d "${INPUT_DIR}" ]]; then
    echo "Error: no existe ${INPUT_DIR}" >&2
    exit 1
fi

flatten_wrapper() {
    local target_dir="$1"
    while true; do
        local entries=("${target_dir}"/*)
        if [[ ${#entries[@]} -ne 1 || ! -d "${entries[0]}" ]]; then
            break
        fi

        local inner_dir="${entries[0]}"
        local inner_entries=("${inner_dir}"/*)
        if [[ ${#inner_entries[@]} -eq 0 ]]; then
            break
        fi

        mv "${inner_dir}"/* "${target_dir}/"
        rmdir "${inner_dir}"
    done
}

extracted=0
skipped=0

for archive in "${INPUT_DIR}"/*; do
    [[ -f "${archive}" ]] || continue
    case "${archive,,}" in
        *.zip|*.rar) ;;
        *) continue ;;
    esac

    name="$(basename "${archive}")"
    if [[ -n "${MATCH}" && "${name}" != *"${MATCH}"* ]]; then
        continue
    fi

    base_name="${name%.*}"
    target_dir="${EVALUATION_DIR}/${FORM_FOLDER}/${base_name}"

    if [[ -e "${target_dir}" ]]; then
        echo "SKIP ${name} -> ${target_dir#${WORKSPACE_ROOT}/} already exists"
        skipped=$((skipped + 1))
        continue
    fi

    mkdir -p "${target_dir}"
    case "${archive,,}" in
        *.zip)
            unzip -q "${archive}" -d "${target_dir}"
            ;;
        *.rar)
            require_command unrar
            unrar x -inul "${archive}" "${target_dir}/"
            ;;
    esac

    flatten_wrapper "${target_dir}"
    echo "OK   ${name} -> ${target_dir#${WORKSPACE_ROOT}/}"
    extracted=$((extracted + 1))
done

echo "Extraction completed: ${extracted} extracted, ${skipped} skipped."
