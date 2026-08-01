#!/usr/bin/env bash
# Runs the C0 security test suite (unittest, stdlib only).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/engine"

exec python3 -m unittest discover -s c0/tests -t . -v "$@"
