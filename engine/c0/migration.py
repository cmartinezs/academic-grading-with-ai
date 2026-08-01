"""Safe legacy data migration to the private root (C0.4).

Dry-run by default. ``apply`` copies roster, results, submissions and evidence from
``evaluations/<SECTION>/`` into ``<private-root>/sections/<SECTION>/``, assigns opaque
student ids, never deletes the origin, records hashes, writes a migration manifest and
an operational ledger without PII, is idempotent, detects partial migrations and
supports technical rollback of copied files.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from c0.identity import IdentityIntegrityError, IdentityStore
from c0.locking import FileLock
from c0.paths import RuntimeConfig

MANIFEST_FILENAME = "migration-manifest.json"
LEDGER_FILENAME_SUFFIX = ".json"
MIGRATION_NOTES_FILENAME = "MIGRATION_NOTES.md"

STATUS_PENDING = "pending"
STATUS_MIGRATED = "migrated"
STATUS_PARTIAL = "partial"
STATUS_ROLLED_BACK = "rolled_back"

SUBMISSION_SOURCE_DIRS = ("submissions", "entregas")
EVIDENCE_SOURCE_DIRS = ("support", "raw/private", "evidencia_drive")
RESULT_GLOB = "form-*/results/*.md"
EVALUATION_SUBDIRS = ("students.json", "assignments.json")
HASH_BLOCK_SIZE = 1024 * 1024  # 1 MiB


class MigrationError(Exception):
    """Base migration error."""


def sha256_file(path: Path, block_size: int = HASH_BLOCK_SIZE) -> str:
    """Compute a SHA-256 over the file in fixed-size blocks (memory-safe for big files)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def workspace_rel(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass
class MigrationItem:
    kind: str
    source: Path
    target: Path
    source_sha256: str
    target_sha256: str
    converted: bool = False
    rename_note: Optional[str] = None

    def to_dict(self, workspace_root: Path) -> dict:
        return {
            "kind": self.kind,
            "source": workspace_rel(self.source, workspace_root),
            "target": workspace_rel(self.target, workspace_root),
            "sourceSha256": self.source_sha256,
            "targetSha256": self.target_sha256,
            "converted": self.converted,
            "renameNote": self.rename_note,
        }


@dataclass
class SectionMigration:
    section_code: str
    legacy_dir: Path
    status: str
    message: str
    items: list[MigrationItem] = field(default_factory=list)
    identity_count: int = 0
    identity_missing: int = 0

    def to_dict(self, workspace_root: Path) -> dict:
        return {
            "sectionCode": self.section_code,
            "status": self.status,
            "message": self.message,
            "identityCount": self.identity_count,
            "identityMissing": self.identity_missing,
            "items": [item.to_dict(workspace_root) for item in self.items],
        }


@dataclass
class MigrationPlan:
    dry_run: bool
    sections: list[SectionMigration] = field(default_factory=list)

    def to_dict(self, workspace_root: Path) -> dict:
        return {
            "dryRun": self.dry_run,
            "sections": [section.to_dict(workspace_root) for section in self.sections],
        }


@dataclass
class MigrationReport:
    applied: list[str]
    skipped: list[str]
    errors: list[str]
    messages: list[str]


@dataclass
class RollbackReport:
    section_code: str
    removed: list[str]
    errors: list[str]


def detect_sections(workspace_root: Path) -> list[Path]:
    evaluations = workspace_root / "evaluations"
    if not evaluations.exists():
        return []
    return sorted(path for path in evaluations.iterdir() if path.is_dir() and (path / "config.json").exists())


def load_students(section_dir: Path) -> list[dict]:
    path = section_dir / "students.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    students = payload.get("students", [])
    return students if isinstance(students, list) else []


def find_legacy_private_files(section_dir: Path) -> list[str]:
    """Return workspace-relative paths of known PII-bearing legacy files (no content)."""
    found: list[Path] = []
    roster = section_dir / "students.json"
    if roster.exists():
        found.append(roster)
    for ev in sorted(path for path in section_dir.iterdir() if path.is_dir()):
        for name in EVALUATION_SUBDIRS:
            candidate = ev / name
            if candidate.exists():
                found.append(candidate)
        for form in sorted(path for path in ev.iterdir() if path.is_dir()):
            if form.name in SUBMISSION_SOURCE_DIRS or form.name.startswith("form-"):
                for sub in sorted((form / "submissions").glob("*")):
                    found.append(sub)
                for result in sorted(form.glob("results/*.md")):
                    found.append(result)
        for directory in EVIDENCE_SOURCE_DIRS:
            candidate = ev / directory
            if candidate.exists():
                for path in sorted(candidate.rglob("*")):
                    if path.is_file():
                        found.append(path)
    for directory in EVIDENCE_SOURCE_DIRS:
        candidate = section_dir / directory
        if candidate.exists():
            for path in sorted(candidate.rglob("*")):
                if path.is_file():
                    found.append(path)
    grades = section_dir / "grades.json"
    if grades.exists():
        found.append(grades)
    return [workspace_rel(path, section_dir.parent.parent) for path in found]


class Migrator:
    def __init__(self, workspace_root: Path, runtime: RuntimeConfig, identity_store: IdentityStore):
        self.workspace_root = Path(workspace_root).resolve()
        self.runtime = runtime
        self.identity_store = identity_store

    def private_section_dir(self, section_code: str) -> Path:
        return self.runtime.private_root / "sections" / section_code

    def ledger_path(self, section_code: str) -> Path:
        return self.runtime.state_root / "migrations" / f"{section_code}{LEDGER_FILENAME_SUFFIX}"

    def lock_path(self, section_code: str) -> Path:
        return self.runtime.state_root / "locks" / f"migrate-{section_code}.lock"

    def _read_ledger(self, section_code: str) -> dict | None:
        path = self.ledger_path(section_code)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _read_manifest(self, section_code: str) -> dict | None:
        path = self.private_section_dir(section_code) / MANIFEST_FILENAME
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _compute_status(self, section_dir: Path) -> str:
        """Status based on ledger, copied targets and source drift vs the manifest."""
        code = section_dir.name
        ledger = self._read_ledger(code)
        if ledger is None:
            return STATUS_PENDING
        if ledger.get("status") == STATUS_ROLLED_BACK:
            return STATUS_ROLLED_BACK
        manifest = self._read_manifest(code)
        if manifest is None:
            return STATUS_PARTIAL

        manifest_items = manifest.get("items", [])
        for item in manifest_items:
            target = self.workspace_root / item["target"]
            if not target.exists():
                return STATUS_PARTIAL
            if sha256_file(target) != item.get("targetSha256"):
                return STATUS_PARTIAL

        items, _, _ = self._collect_items(section_dir)
        fresh_by_source = {workspace_rel(item.source, self.workspace_root): item for item in items}
        manifest_by_source = {item["source"]: item for item in manifest_items}

        for source, manifest_item in manifest_by_source.items():
            fresh = fresh_by_source.get(source)
            if fresh is None:
                continue
            if fresh.source_sha256 != manifest_item.get("sourceSha256"):
                return STATUS_PARTIAL
        for source in fresh_by_source:
            if source not in manifest_by_source:
                return STATUS_PARTIAL
        return STATUS_MIGRATED

    def build_plan(self, requested: Optional[Iterable[str]] = None, dry_run: bool = True) -> MigrationPlan:
        plan = MigrationPlan(dry_run=dry_run)
        requested_set = set(requested or [])
        for section_dir in detect_sections(self.workspace_root):
            code = section_dir.name
            if requested_set and code not in requested_set:
                continue
            plan.sections.append(self._plan_section(section_dir))
        return plan

    def _collect_items(self, section_dir: Path) -> tuple[list[MigrationItem], int, int]:
        code = section_dir.name
        private_section = self.private_section_dir(code)
        items: list[MigrationItem] = []
        identity_count = 0
        identity_missing = 0

        roster = section_dir / "students.json"
        students = load_students(section_dir)
        if roster.exists():
            items.append(
                MigrationItem(
                    kind="roster",
                    source=roster,
                    target=private_section / "roster" / "students.json",
                    source_sha256=sha256_file(roster),
                    target_sha256="",
                    converted=True,
                )
            )
        for student in students:
            rut = str(student.get("rut") or "").strip()
            if not rut:
                identity_missing += 1
                continue
            identity_count += 1

        for ev in sorted(path for path in section_dir.iterdir() if path.is_dir()):
            for name in EVALUATION_SUBDIRS:
                candidate = ev / name
                if candidate.exists():
                    items.append(
                        MigrationItem(
                            kind="roster",
                            source=candidate,
                            target=private_section / "roster" / f"{ev.name}-{name}",
                            source_sha256=sha256_file(candidate),
                            target_sha256=sha256_file(candidate),
                        )
                    )
            for form in sorted(path for path in ev.iterdir() if path.is_dir()):
                if not (form.name.startswith("form-") or form.name in SUBMISSION_SOURCE_DIRS):
                    continue
                submissions_dir = form / "submissions"
                if submissions_dir.exists():
                    for path in sorted(submissions_dir.rglob("*")):
                        if path.is_file():
                            items.append(
                                MigrationItem(
                                    kind="submissions",
                                    source=path,
                                    target=private_section / "submissions" / form.name / path.relative_to(submissions_dir),
                                    source_sha256=sha256_file(path),
                                    target_sha256=sha256_file(path),
                                )
                            )
                results_dir = form / "results"
                if results_dir.exists():
                    for result in sorted(results_dir.glob("*.md")):
                        target = private_section / "results" / form.name / result.name
                        rename_note = None
                        if result.stem and not result.stem.startswith("stu_"):
                            mapped = self.identity_store.resolve_by_external("rut", result.stem)
                            if mapped:
                                target = private_section / "results" / form.name / f"{mapped}.md"
                                rename_note = f"renamed from {result.name}"
                        items.append(
                            MigrationItem(
                                kind="results",
                                source=result,
                                target=target,
                                source_sha256=sha256_file(result),
                                target_sha256=sha256_file(result),
                                rename_note=rename_note,
                            )
                        )
            for directory in EVIDENCE_SOURCE_DIRS:
                candidate = ev / directory
                if candidate.exists():
                    for path in sorted(candidate.rglob("*")):
                        if path.is_file():
                            items.append(
                                MigrationItem(
                                    kind="evidence",
                                    source=path,
                                    target=private_section / "evidence" / directory / path.relative_to(candidate),
                                    source_sha256=sha256_file(path),
                                    target_sha256=sha256_file(path),
                                )
                            )

        for directory in EVIDENCE_SOURCE_DIRS:
            candidate = section_dir / directory
            if candidate.exists():
                for path in sorted(candidate.rglob("*")):
                    if path.is_file():
                        items.append(
                            MigrationItem(
                                kind="evidence",
                                source=path,
                                target=private_section / "evidence" / directory / path.relative_to(candidate),
                                source_sha256=sha256_file(path),
                                target_sha256=sha256_file(path),
                            )
                        )

        for name in ("config.json", "grades.json", "evaluations.json"):
            candidate = section_dir / name
            if not candidate.exists():
                continue
            folder = "results" if name == "grades.json" else "evidence"
            items.append(
                MigrationItem(
                    kind="config" if name == "config.json" else "results" if name == "grades.json" else "evidence",
                    source=candidate,
                    target=private_section / folder / name,
                    source_sha256=sha256_file(candidate),
                    target_sha256=sha256_file(candidate),
                )
            )

        return items, identity_count, identity_missing

    def _plan_section(self, section_dir: Path) -> SectionMigration:
        code = section_dir.name
        items, identity_count, identity_missing = self._collect_items(section_dir)
        status = self._compute_status(section_dir)
        if identity_missing > 0 and status == STATUS_MIGRATED:
            status = STATUS_PARTIAL
        section = SectionMigration(
            section_code=code,
            legacy_dir=section_dir,
            status=status,
            message="",
            items=items,
            identity_count=identity_count,
            identity_missing=identity_missing,
        )
        if status == STATUS_PENDING:
            section.message = f"Pending migration for {code}: {len(items)} items, {identity_count} identities."
        elif status == STATUS_PARTIAL:
            if identity_missing > 0:
                section.message = f"Partial migration for {code}: {identity_missing} student(s) lack an identifier."
            else:
                section.message = f"Partial migration detected for {code}; re-run apply to complete."
        elif status == STATUS_ROLLED_BACK:
            section.message = f"Migration for {code} was rolled back; apply again to migrate."
        else:
            section.message = f"{code} is already migrated and verified."
        return section

    def apply(self, plan: MigrationPlan) -> MigrationReport:
        report = MigrationReport(applied=[], skipped=[], errors=[], messages=[])
        for section in plan.sections:
            self._apply_section(section, report)
        return report

    def _apply_section(self, section: SectionMigration, report: MigrationReport) -> None:
        code = section.section_code
        status = self._compute_status(section.legacy_dir)
        if status == STATUS_MIGRATED:
            report.skipped.append(code)
            report.messages.append(f"{code}: already migrated, nothing to do.")
            return
        try:
            with FileLock(self.lock_path(code)):
                if self._compute_status(section.legacy_dir) == STATUS_MIGRATED:
                    report.skipped.append(code)
                    report.messages.append(f"{code}: already migrated, nothing to do.")
                    return
                self._do_apply(section)
            report.applied.append(code)
            report.messages.append(f"{code}: migration applied.")
        except Exception as exc:  # noqa: BLE001 - surface all migration errors
            report.errors.append(f"{code}: {exc}")
            report.messages.append(f"{code}: migration failed: {exc}")

    def _do_apply(self, section: SectionMigration) -> None:
        code = section.section_code
        if self.identity_store.integrity_issues():
            raise IdentityIntegrityError(
                "Identity store has integrity issues; refusing to migrate without a consistent identity store."
            )
        self.runtime.ensure_dirs()
        private_section = self.private_section_dir(code)
        private_section.mkdir(parents=True, exist_ok=True)

        students = load_students(section.legacy_dir)
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
        student_ids = self.identity_store.ensure_many(entries)
        mapping: dict[str, str] = {
            str(entries[index]["external"]["rut"]).strip(): student_id
            for index, student_id in enumerate(student_ids)
        }

        roster_target = private_section / "roster" / "students.json"
        if (section.legacy_dir / "students.json").exists():
            converted = self._convert_roster(students, mapping)
            self._write_private(roster_target, json.dumps(converted, indent=2, ensure_ascii=False) + "\n")

        for item in section.items:
            if item.kind == "roster" and item.target == roster_target and item.converted:
                item.target_sha256 = sha256_file(roster_target)
                continue
            if item.kind == "results" and not item.source.stem.startswith("stu_"):
                mapped = mapping.get(item.source.stem)
                if mapped:
                    form_name = item.source.parent.parent.name
                    item.target = private_section / "results" / form_name / f"{mapped}.md"
                    item.rename_note = f"renamed from {item.source.name}"
            item.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, item.target)
            os.chmod(item.target, 0o600)
            item.target_sha256 = sha256_file(item.target)

        manifest = {
            "schemaVersion": 1,
            "sectionCode": code,
            "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "identityCount": section.identity_count,
            "items": [item.to_dict(self.workspace_root) for item in section.items],
        }
        self._write_private(private_section / MANIFEST_FILENAME, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        self._write_private(private_section / MIGRATION_NOTES_FILENAME, self._notes(code))

        ledger = {
            "schemaVersion": 1,
            "sectionCode": code,
            "status": STATUS_MIGRATED,
            "appliedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "identityCount": section.identity_count,
            "itemCount": len(section.items),
            "manifestPath": workspace_rel(private_section / MANIFEST_FILENAME, self.workspace_root),
        }
        self._write_private(self.ledger_path(code), json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")

    def _write_private(self, path: Path, content: str) -> None:
        """Write a sensitive file atomically with owner-only permissions."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".mig-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def _convert_roster(self, students: list[dict], mapping: dict[str, str]) -> dict:
        converted_students = []
        for student in students:
            rut = str(student.get("rut") or "").strip()
            row = {"studentId": mapping.get(rut, ""), "externalIdentifiers": {"rut": rut}}
            for key in ("order", "lastName", "secondLastName", "names", "fullName", "repoUrl", "avaUser", "email"):
                if student.get(key) is not None:
                    row[key] = student[key]
            converted_students.append(row)
        return {"schemaVersion": 1, "students": converted_students}

    def _notes(self, code: str) -> str:
        return (
            f"# Migration notes — {code}\n"
            "\n"
            "Private data for this section was copied to the private runtime root.\n"
            "Origin files under evaluations/<SECTION>/ were NOT deleted by this tool.\n"
            "\n"
            "After verifying the copy, the following can be removed manually:\n"
            "\n"
            f"- evaluations/{code}/students.json\n"
            f"- evaluations/{code}/<EV>/students.json and evaluations/{code}/<EV>/assignments.json\n"
            f"- evaluations/{code}/<EV>/form-*/results/\n"
            f"- evaluations/{code}/<EV>/form-*/submissions/\n"
            f"- evaluations/{code}/grades.json\n"
            "\n"
            "See docs/implementation/C0-RUNBOOKS.md for the safe deletion runbook.\n"
        )

    def rollback(self, section_code: str) -> RollbackReport:
        report = RollbackReport(section_code=section_code, removed=[], errors=[])
        private_section = self.private_section_dir(section_code)
        manifest = self._read_manifest(section_code)
        if manifest is None:
            report.errors.append(f"No manifest found for {section_code}; nothing to roll back.")
            return report
        try:
            with FileLock(self.lock_path(section_code)):
                for item in manifest.get("items", []):
                    target = self.workspace_root / item["target"]
                    if target.exists():
                        if sha256_file(target) == item["targetSha256"]:
                            target.unlink()
                            report.removed.append(item["target"])
                        else:
                            report.errors.append(f"Target {item['target']} was modified; skipped.")
                if report.errors:
                    return report
                manifest_path = private_section / MANIFEST_FILENAME
                if manifest_path.exists():
                    manifest_path.unlink()
                notes = private_section / MIGRATION_NOTES_FILENAME
                if notes.exists():
                    notes.unlink()
                self._write_ledger_status(section_code, STATUS_ROLLED_BACK)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(str(exc))
        return report

    def _write_ledger_status(self, section_code: str, status: str) -> None:
        ledger_path = self.ledger_path(section_code)
        payload = self._read_ledger(section_code) or {}
        payload.update(
            {
                "schemaVersion": 1,
                "sectionCode": section_code,
                "status": status,
                "appliedAt": payload.get("appliedAt"),
                "rolledBackAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
        self._write_private(ledger_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
