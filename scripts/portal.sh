#!/usr/bin/env bash
# portal — C4 secure student portal CLI wrapper. Usage:
#   ./scripts/portal.sh <command> [args...]
#   ./scripts/portal.sh test   # synthetic self-check
#
# Exit codes follow the C4 contract: 0 success, 1 usage/config,
# 2 validation/security/approval gate, 3 partial/blocked/operational.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

if [[ "${1:-}" == "test" ]]; then
    python3 "${ENGINE_SCRIPTS_DIR}/portal_test.py"
    exit $?
fi

python3 "${ENGINE_SCRIPTS_DIR}/portal.py" "$@"
