#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3
require_course_config

python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null
python3 "${ENGINE_SCRIPTS_DIR}/export-publication-data.py"
python3 "${ENGINE_SCRIPTS_DIR}/sync-section-indexes.py" --section "${SECTION_CODE}" >/dev/null

echo "Export generated in exports/publication-input/"
