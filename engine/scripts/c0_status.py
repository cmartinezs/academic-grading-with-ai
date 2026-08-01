#!/usr/bin/env python3
"""c0-status — workspace security status and gates.

Read-only. Prints PASS/WARN/FAIL findings. Exit codes: 2 on FAIL, 1 on WARN with
``--strict``, 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from c0.status import FAIL, WARN, run_security_checks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Workspace security status (C0.7).")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on WARN findings too.")
    parser.add_argument("--workspace", help="Workspace root (defaults to repository root).")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else ROOT
    report = run_security_checks(workspace)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"# C0 security status")
        print(f"Root: {report.root}")
        print(f"State: {report.worst_state()}")
        for finding in report.findings:
            print(f"[{finding.state}] {finding.check}: {finding.message}")

    if report.worst_state() == FAIL:
        return 2
    if args.strict and report.worst_state() == WARN:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
