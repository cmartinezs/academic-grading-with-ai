#!/usr/bin/env bash
# grade-policy — C2 grade policy engine CLI wrapper
# (validate/calculate/explain/registry/test). Usage:
#   ./scripts/grade-policy.sh validate <policy.json>
#   ./scripts/grade-policy.sh calculate <policy.json> --inputs <inputs.json> [--section <SECTION>]
#   ./scripts/grade-policy.sh test
#
# Exit codes follow the C2 contract: 0 success, 1 usage/invalid state, 2 gate failure.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

if [[ "${1:-}" == "test" ]]; then
    python3 "${ENGINE_SCRIPTS_DIR}/grade_policy_test.py"
    exit $?
fi

python3 "${ENGINE_SCRIPTS_DIR}/grade_policy.py" "$@"
