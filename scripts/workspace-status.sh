#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

require_command python3

python3 "${ENGINE_SCRIPTS_DIR}/workspace_status.py" "$@"
