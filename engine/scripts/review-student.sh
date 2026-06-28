#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <submission-path>" >&2
    exit 1
fi

DELIVERY_DIR="$(realpath "$1")"

if [[ ! -d "${DELIVERY_DIR}" ]]; then
    echo "Error: the specified folder does not exist: ${DELIVERY_DIR}" >&2
    exit 1
fi

mapfile -d '' PSC_FILES < <(find "${DELIVERY_DIR}" -type f \( -iname '*.psc' -o -iname '*.pseint' \) -print0 | sort -z)
mapfile -d '' ARCHIVES < <(find "${DELIVERY_DIR}" -type f \( -iname '*.zip' -o -iname '*.rar' \) -print0 | sort -z)

echo "=== SUBMISSION ==="
echo "Folder: ${DELIVERY_DIR}"
student_id="$(basename "${DELIVERY_DIR}" | sed -E 's/^([0-9]+).*$/\1/')"
result_file="$(dirname "${DELIVERY_DIR}")/results/${student_id}.md"
if [[ "${student_id}" =~ ^[0-9]+$ && -f "${result_file}" ]]; then
    echo "Result: ${result_file#$(dirname "${DELIVERY_DIR}")/} present"
else
    echo "Result: no `results/<studentId>.md`"
fi
echo ""
echo "=== PSEINT FILES ==="

if [[ ${#PSC_FILES[@]} -eq 0 ]]; then
    echo "No *.psc or *.pseint files found"
    exit 1
fi

echo "Count: ${#PSC_FILES[@]}"
for file in "${PSC_FILES[@]}"; do
    rel="${file#${DELIVERY_DIR}/}"
    lines="$(wc -l < "${file}" | tr -d ' ')"
    echo "- ${rel} (${lines} lines)"
done

echo ""
echo "=== STRUCTURAL SUPPORT ==="
echo "Subfolders: $(find "${DELIVERY_DIR}" -mindepth 1 -type d | wc -l | tr -d ' ')"
echo "Nested archives: ${#ARCHIVES[@]}"
