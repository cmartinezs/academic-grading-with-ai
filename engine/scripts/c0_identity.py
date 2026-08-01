#!/usr/bin/env python3
"""c0-identity — opaque student identity management.

Read-only by default. ``--assign`` with ``--apply`` persists identity records in the
private state root. Reports never include PII: external identifiers are masked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from c0.identity import IdentityConflictError, IdentityIntegrityError, IdentityStore  # noqa: E402
from c0.paths import RuntimeConfigError, resolve_runtime_roots  # noqa: E402
from c0.util import mask_value  # noqa: E402


def section_dirs(workspace: Path) -> list[Path]:
    evaluations = workspace / "evaluations"
    if not evaluations.exists():
        return []
    return sorted(path for path in evaluations.iterdir() if path.is_dir() and (path / "config.json").exists())


def load_students(section_dir: Path) -> list[dict]:
    path = section_dir / "students.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    students = payload.get("students", [])
    return students if isinstance(students, list) else []


def report_status(workspace: Path, store: IdentityStore, section_code: str | None, as_json: bool) -> dict:
    sections = section_dirs(workspace)
    if section_code:
        sections = [path for path in sections if path.name == section_code]
        if not sections:
            raise SystemExit(f"Error: section {section_code} not found.")

    report: dict = {"storeExists": store.path.exists(), "records": store.count(), "sections": []}
    for section in sections:
        students = load_students(section)
        resolved = 0
        missing = 0
        for student in students:
            rut = str(student.get("rut") or "").strip()
            if not rut:
                continue
            if store.resolve_by_external("rut", rut):
                resolved += 1
            else:
                missing += 1
        report["sections"].append(
            {
                "code": section.name,
                "students": len(students),
                "resolved": resolved,
                "missing": missing,
            }
        )
    return report


def cmd_status(args: argparse.Namespace, store: IdentityStore, workspace: Path) -> int:
    report = report_status(workspace, store, args.section, args.json)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("# Opaque identity status")
    print(f"Store: {store.path}")
    print(f"Records: {report['records']}")
    for section in report["sections"]:
        print(f"- {section['code']}: students={section['students']} resolved={section['resolved']} missing={section['missing']}")
    issues = store.integrity_issues()
    if issues:
        print("Integrity issues:")
        for issue in issues:
            print(f"  - {issue}")
        return 2
    return 0


def cmd_list(args: argparse.Namespace, store: IdentityStore) -> int:
    rows = [record.to_dict() for record in sorted(store.all(), key=lambda r: r.student_id)]
    if args.json:
        for row in rows:
            row["externalIdentifiers"] = {k: mask_value(v) for k, v in row["externalIdentifiers"].items()}
        print(json.dumps({"records": rows}, indent=2, ensure_ascii=False))
        return 0
    for record in sorted(store.all(), key=lambda r: r.student_id):
        masked = ", ".join(f"{k}={mask_value(v)}" for k, v in record.external_identifiers.items())
        print(f"{record.student_id}  {masked}")
    return 0


def cmd_assign(args: argparse.Namespace, store: IdentityStore, runtime, workspace: Path) -> int:
    if not args.section:
        print("Error: --section is required for --assign.", file=sys.stderr)
        return 2
    sections = section_dirs(workspace)
    section = next((path for path in sections if path.name == args.section), None)
    if section is None:
        print(f"Error: section {args.section} not found.", file=sys.stderr)
        return 2
    issues = store.integrity_issues()
    if issues:
        print("Error: identity store has integrity issues; fix them before assigning.", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2
    if args.apply:
        runtime.ensure_dirs()
    students = load_students(section)
    entries = []
    for student in students:
        rut = str(student.get("rut") or "").strip()
        if not rut:
            continue
        external = {"rut": rut}
        if student.get("email"):
            external["email"] = str(student["email"])
        entries.append(
            {
                "external": external,
                "display_name": student.get("fullName") or student.get("names"),
                "contact": {"avaUser": student.get("avaUser")} if student.get("avaUser") else None,
            }
        )
    try:
        student_ids = store.ensure_many(entries, dry_run=not args.apply)
    except IdentityIntegrityError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except IdentityConflictError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    rows = []
    for entry, sid in zip(entries, student_ids):
        rut = entry["external"]["rut"]
        rows.append({"studentId": sid, "rut": mask_value(rut), "action": "created" if args.apply else "planned"})
    if args.json:
        print(json.dumps({"dryRun": not args.apply, "records": rows}, indent=2, ensure_ascii=False))
        return 0
    print(f"# Assign opaque identities for {args.section}")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")
    for row in rows:
        print(f"{row['action']:<8} {row['studentId']}  rut={row['rut']}")
    return 0


def cmd_check(args: argparse.Namespace, store: IdentityStore) -> int:
    issues = store.integrity_issues()
    if args.json:
        print(json.dumps({"issues": issues, "records": store.count()}, indent=2, ensure_ascii=False))
        return 2 if issues else 0
    print(f"Records: {store.count()}")
    if issues:
        print("Integrity issues:")
        for issue in issues:
            print(f"  - {issue}")
        return 2
    print("No integrity issues.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Opaque student identity management (C0.3).")
    parser.add_argument("--section", help="Section code to operate on.")
    parser.add_argument("--assign", action="store_true", help="Ensure opaque ids for the section roster.")
    parser.add_argument("--apply", action="store_true", help="Persist changes (assign defaults to dry-run).")
    parser.add_argument("--status", action="store_true", help="Report identity coverage (default).")
    parser.add_argument("--list", action="store_true", help="List stored identities with masked external ids.")
    parser.add_argument("--check", action="store_true", help="Check identity store integrity.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--workspace", help="Workspace root (defaults to repository root).")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else ROOT
    try:
        runtime = resolve_runtime_roots(workspace)
    except RuntimeConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    store = IdentityStore(runtime.state_root / "identity")

    if args.assign:
        return cmd_assign(args, store, runtime, workspace)
    if args.list:
        return cmd_list(args, store)
    if args.check:
        return cmd_check(args, store)
    return cmd_status(args, store, workspace)


if __name__ == "__main__":
    sys.exit(main())
