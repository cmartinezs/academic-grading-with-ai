#!/usr/bin/env python3
"""c0-migrate — safe legacy data migration to the private root.

Dry-run by default. ``--apply`` copies data (never deletes the origin) and records
state without PII. ``--rollback`` removes copied files verified by hash.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from c0.identity import IdentityStore  # noqa: E402
from c0.migration import Migrator, detect_sections  # noqa: E402
from c0.paths import RuntimeConfigError, resolve_runtime_roots  # noqa: E402


def print_plan(plan, as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan.to_dict(ROOT), indent=2, ensure_ascii=False))
        return
    print("# Migration plan (dry-run)" if plan.dry_run else "# Migration plan")
    for section in plan.sections:
        print(f"- {section.section_code}: status={section.status} items={len(section.items)} identities={section.identity_count}")
        print(f"    {section.message}")


def print_report(report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
        return
    print("# Migration result")
    for message in report.messages:
        print(f"- {message}")


def print_rollback(report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.__dict__, indent=2, ensure_ascii=False))
        return
    print(f"# Rollback {report.section_code}")
    for path in report.removed:
        print(f"- removed {path}")
    for error in report.errors:
        print(f"- error: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe legacy data migration (C0.4).")
    parser.add_argument("--section", help="Migrate only this section.")
    parser.add_argument("--apply", action="store_true", help="Apply the migration (default is dry-run).")
    parser.add_argument("--rollback", metavar="SECTION", help="Roll back copied files for a section.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--workspace", help="Workspace root (defaults to repository root).")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else ROOT
    try:
        runtime = resolve_runtime_roots(workspace)
    except RuntimeConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    identity_store = IdentityStore(runtime.state_root / "identity")
    migrator = Migrator(workspace, runtime, identity_store)

    requested = [args.section] if args.section else None

    if args.rollback:
        report = migrator.rollback(args.rollback)
        print_rollback(report, args.json)
        return 2 if report.errors else 0

    try:
        plan = migrator.build_plan(requested, dry_run=not args.apply)
        print_plan(plan, args.json)
        if not args.apply:
            return 0
        report = migrator.apply(plan)
        print_report(report, args.json)
        if report.errors:
            return 2
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
