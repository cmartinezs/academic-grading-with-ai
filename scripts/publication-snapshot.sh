#!/usr/bin/env bash
# publication-snapshot — C1 CLI wrapper (build/verify/review/approve/status/
# transition/compatibility). Usage:
#   ./scripts/publication-snapshot.sh --section <SECTION_CODE> <command> [args...]
#   ./scripts/publication-snapshot.sh test   # synthetic self-check
#
# Exit codes follow the C1 contract: 0 success, 1 usage/invalid state, 2 gate failure.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

if [[ "${1:-}" == "test" ]]; then
    python3 "${ENGINE_SCRIPTS_DIR}/publication_snapshot_test.py"
    exit $?
fi

python3 "${ENGINE_SCRIPTS_DIR}/publication_snapshot.py" "$@"
