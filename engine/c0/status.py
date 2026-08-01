"""Workspace security status and gates (C0.7).

Read-only diagnostic. States: PASS / WARN / FAIL. PII or secrets, unsafe data roots
or versionable private data are FAIL. Pending migrations are WARN during transition.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from c0 import git
from c0.identity import IdentityStore
from c0.migration import Migrator, STATUS_MIGRATED, detect_sections, find_legacy_private_files
from c0.paths import (
    RuntimeConfigError,
    ZoneClassification,
    classify_zone,
    resolve_runtime_roots,
)
from c0.scanner import Scanner, SEVERITY_BLOCK, SEVERITY_REVIEW

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class StatusFinding:
    state: str
    check: str
    message: str

    def to_dict(self) -> dict:
        return {"state": self.state, "check": self.check, "message": self.message}


@dataclass
class StatusReport:
    root: str
    findings: list[StatusFinding] = field(default_factory=list)

    def worst_state(self) -> str:
        if any(f.state == FAIL for f in self.findings):
            return FAIL
        if any(f.state == WARN for f in self.findings):
            return WARN
        return PASS

    def to_dict(self) -> dict:
        return {"root": self.root, "state": self.worst_state(), "findings": [f.to_dict() for f in self.findings]}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def run_security_checks(workspace_root: Path, env: Optional[Mapping[str, str]] = None) -> StatusReport:
    root = Path(workspace_root).resolve()
    report = StatusReport(root=str(root))
    env = dict(os.environ) if env is None else dict(env)

    try:
        runtime = resolve_runtime_roots(root, env=env)
    except RuntimeConfigError as exc:
        report.findings.append(StatusFinding(FAIL, "config-resolution", f"Runtime configuration failed closed: {exc}"))
        report.findings.append(StatusFinding(FAIL, "private-root", "Cannot verify private data root; configuration is blocking."))
        report.findings.append(StatusFinding(FAIL, "state-root", "Cannot verify state root; configuration is blocking."))
        report.findings.append(StatusFinding(FAIL, "identity", "Identity store cannot be checked; configuration is blocking."))
        report.findings.append(StatusFinding(FAIL, "pending-migration", "Migration cannot be checked; configuration is blocking."))
        return report

    for name, path in (
        ("private-root", runtime.private_root),
        ("state-root", runtime.state_root),
        ("publications-root", runtime.publications_root),
        ("temp-root", runtime.temp_root),
    ):
        classification = classify_zone(path, root)
        if classification in (
            ZoneClassification.UNSAFE_TRACKED,
            ZoneClassification.UNSAFE_NOT_IGNORED,
            ZoneClassification.UNSAFE_UNKNOWN,
        ):
            report.findings.append(
                StatusFinding(FAIL, name, f"Unsafe data root: {path} ({classification.value}).")
            )
        elif classification == ZoneClassification.SAFE_IGNORED:
            report.findings.append(
                StatusFinding(PASS, name, f"{path} is inside the repository but fully Git-ignored.")
            )
        else:
            report.findings.append(StatusFinding(PASS, name, f"{path} is outside the Git worktree."))

    if not runtime.private_root.exists():
        report.findings.append(StatusFinding(WARN, "private-root", "Private data root does not exist yet; migrate legacy data."))
    if not runtime.state_root.exists():
        report.findings.append(StatusFinding(WARN, "state-root", "State root does not exist yet."))

    perms = _check_permissions(runtime.private_root)
    if perms:
        report.findings.append(StatusFinding(WARN, "permissions", perms))
    perms = _check_permissions(runtime.state_root)
    if perms:
        report.findings.append(StatusFinding(WARN, "permissions", perms))

    scanner = Scanner()
    findings = scanner.scan_files([(_rel(path, root), path) for path in git.tracked_files(root) if path.is_file()])
    blocked = [f for f in findings if f.severity == SEVERITY_BLOCK]
    reviewed = [f for f in findings if f.severity == SEVERITY_REVIEW]
    if blocked:
        report.findings.append(
            StatusFinding(FAIL, "versionable-private-data", f"Versioned data with PII/secrets: {len(blocked)} BLOCK finding(s).")
        )
    elif reviewed:
        report.findings.append(
            StatusFinding(WARN, "versionable-private-data", f"Versioned data with {len(reviewed)} REVIEW finding(s).")
        )
    else:
        report.findings.append(StatusFinding(PASS, "versionable-private-data", "No PII/secret findings in tracked files."))

    identity_store = IdentityStore(runtime.state_root / "identity")
    issues = identity_store.integrity_issues()
    if issues:
        report.findings.append(StatusFinding(FAIL, "identity", f"Identity store integrity issues: {len(issues)}."))
    elif identity_store.count() == 0 and detect_sections(root):
        report.findings.append(StatusFinding(WARN, "identity", "No opaque identities assigned yet; run c0-migrate."))
    else:
        report.findings.append(StatusFinding(PASS, "identity", f"Identity store consistent ({identity_store.count()} records)."))

    migrator = Migrator(root, runtime, identity_store)
    sections = detect_sections(root)
    if not sections:
        report.findings.append(StatusFinding(PASS, "pending-migration", "No legacy sections detected."))
    else:
        pending = 0
        migrated = 0
        for section_dir in sections:
            plan = migrator.build_plan([section_dir.name])
            section = plan.sections[0]
            if section.status == STATUS_MIGRATED:
                migrated += 1
            else:
                pending += 1
                report.findings.append(
                    StatusFinding(
                        WARN,
                        "pending-migration",
                        f"Section {section.section_code} has status '{section.status}'.",
                    )
                )
        if pending == 0:
            report.findings.append(StatusFinding(PASS, "pending-migration", f"{migrated} section(s) migrated."))

    legacy_files = [path for section_dir in sections for path in find_legacy_private_files(section_dir)]
    if legacy_files:
        report.findings.append(
            StatusFinding(
                WARN,
                "legacy-compatibility",
                f"Legacy private data still present under evaluations/ ({len(legacy_files)} files); migrate before deleting.",
            )
        )
    else:
        report.findings.append(StatusFinding(PASS, "legacy-compatibility", "No legacy private files under evaluations/."))

    if not sections:
        report.findings.append(StatusFinding(PASS, "legacy-compatibility", "Legacy compatibility flow active (no sections yet)."))

    return report


def _check_permissions(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    mode = path.stat().st_mode
    if stat.S_IMODE(mode) & 0o077:
        return f"{path} permissions are {oct(stat.S_IMODE(mode))}; expected owner-only (0o700)."
    return None


def findings_for_workspace_status(report: StatusReport) -> list[dict]:
    """Convert C0 findings to the legacy workspace_status finding shape."""
    converted = []
    for finding in report.findings:
        level = "ERROR" if finding.state == FAIL else ("WARN" if finding.state == WARN else "OK")
        converted.append({"level": level, "path": finding.check, "message": finding.message})
    return converted
