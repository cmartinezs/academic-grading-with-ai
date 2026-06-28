#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_DIR="${ROOT}/onboarding/data/03-submissions-source"
OUT_DIR="${ROOT}/onboarding/work/ava-downloads"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

python3 - <<PY
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

source = Path("${SOURCE_DIR}")
out = Path("${OUT_DIR}")

for form_dir in sorted(source.glob("form-*")):
    if not form_dir.is_dir():
        continue
    target_form = out / form_dir.name
    target_form.mkdir(parents=True, exist_ok=True)
    for submission in sorted(form_dir.iterdir()):
        if not submission.is_dir():
            continue
        zip_path = target_form / f"{submission.name}.zip"
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
            for file_path in sorted(submission.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(submission))
        print(f"created {zip_path.relative_to(out.parent.parent)}")
PY

echo ""
echo "Simulated AVA download generated in ${OUT_DIR#${ROOT}/}/"
