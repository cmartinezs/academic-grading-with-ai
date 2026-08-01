"""C1 gates G4–G8: contract, semantic, privacy, manifest and lifecycle.

Fail-closed: any finding makes the snapshot fail verification. Build-time gates
G0–G3 live in :mod:`builder`; the verifier covers an existing snapshot directory
(staging draft, reviewed draft, or approved snapshot).
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import schemas
from .adapter import ALLOWED_STATUSES, PII_KEYS
from .hashing import content_file_entries, expected_file_meta, review_hash
from .jsonutil import compute_content_hash, is_content_file, read_json, sha256_file

_RE_RUT = re.compile(r"\b(?:\d{1,2}\.\d{3}\.\d{2,3}|\d{6,8})-[\dKk]\b")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_WINDOWS_ABS = re.compile(r"(?:^|[\s([\"'=:])[A-Za-z]:[\\/][A-Za-z0-9_.\\% -]*[A-Za-z0-9_.\\%]")
_RE_UNC_ABS = re.compile(r"(?:^|[\s([\"'=:])\\\\\\[A-Za-z0-9_.\\-]+")
_RE_FILE_URL = re.compile(r"(?i)file://[A-Za-z0-9_./\\%-]+")
_RE_POSIX_ABS = re.compile(r"(?:^|[\s([\"'=:])/(?:[A-Za-z0-9_.~%-]+/)+[A-Za-z0-9_.~% -]*")

CANONICAL_PREFIX = "canonical/"


@dataclass
class VerifyFinding:
    gate: str
    message: str


@dataclass
class VerifyReport:
    root: Path
    findings: list[VerifyFinding] = field(default_factory=list)

    def passed(self) -> bool:
        return not self.findings

    def add(self, gate: str, message: str) -> None:
        self.findings.append(VerifyFinding(gate, message))

    def gate_findings(self, gate: str) -> list[str]:
        return [finding.message for finding in self.findings if finding.gate == gate]

    def summary(self) -> str:
        if self.passed():
            return "OK"
        return f"FAIL ({len(self.findings)} finding(s))"


def _walk_files(root: Path) -> dict[str, Path]:
    """Map relative path -> Path for every regular file under root."""
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            files[rel] = path
    return files


def _json_payload(path: Path) -> Optional[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _contains_pii(text: str) -> bool:
    return bool(_RE_RUT.search(text) or _RE_EMAIL.search(text))


def _iter_keys(payload):
    if isinstance(payload, dict):
        yield from payload.keys()
        for value in payload.values():
            yield from _iter_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_keys(item)


def gate_contract(report: VerifyReport, root: Path, files: dict[str, Path]) -> None:
    """G4 — every JSON document validates against its declared schema."""
    for rel, path in files.items():
        if not rel.endswith(".json"):
            report.add("G4-contract", f"Unexpected non-JSON file: {rel}")
            continue
        payload = _json_payload(path)
        if payload is None:
            report.add("G4-contract", f"File is not a valid JSON object: {rel}")
            continue
        if rel == "manifest.json":
            declared = payload.get("schemaVersion")
            try:
                schemas.require_supported_major(declared)
            except Exception as exc:
                report.add("G4-contract", f"{rel}: {exc}")
        errors = schemas.validate_document(rel, payload)
        for error in errors:
            report.add("G4-contract", f"{rel}: {error}")


def gate_semantic(report: VerifyReport, root: Path, files: dict[str, Path]) -> None:
    """G5 — unique ids, resolvable references, preserved fields, valid relations."""
    section = _json_payload(files.get("canonical/section.json", root / "missing"))
    subjects = _json_payload(files.get("canonical/subjects.json", root / "missing"))
    assessments = _json_payload(files.get("canonical/assessments.json", root / "missing"))
    results = _json_payload(files.get("canonical/results.json", root / "missing"))
    policy = _json_payload(files.get("canonical/policy.json", root / "missing"))
    manifest = _json_payload(files.get("manifest.json", root / "missing"))

    if section is None or subjects is None or assessments is None or results is None or policy is None or manifest is None:
        report.add("G5-semantic", "Missing canonical files for semantic validation.")
        return

    def duplicates(seq):
        seen = set()
        dupes = set()
        for item in seq:
            if item in seen:
                dupes.add(item)
            seen.add(item)
        return sorted(dupes)

    subject_ids = [item.get("studentId") for item in subjects.get("subjects", [])]
    assessment_ids = [item.get("assessmentId") for item in assessments.get("assessments", [])]
    attempt_ids = [item.get("attemptId") for item in results.get("results", [])]

    for label, dupes in (
        ("studentId", duplicates(subject_ids)),
        ("assessmentId", duplicates(assessment_ids)),
        ("attemptId", duplicates(attempt_ids)),
    ):
        if dupes:
            report.add("G5-semantic", f"Duplicate {label}: {dupes}")

    section_ids = set(section.get("assessmentIds") or [])
    if section_ids != set(assessment_ids):
        report.add(
            "G5-semantic",
            f"section.assessmentIds ({sorted(section_ids)}) != assessments ids ({sorted(assessment_ids)}).",
        )

    weight_keys = set(policy.get("evaluationWeights") or {})
    if weight_keys != set(assessment_ids):
        report.add(
            "G5-semantic",
            f"policy.evaluationWeights keys ({sorted(weight_keys)}) != assessments ids ({sorted(assessment_ids)}).",
        )

    subject_set = set(subject_ids)
    for result in results.get("results", []):
        sid = result.get("studentId")
        aid = result.get("assessmentId")
        if sid not in subject_set:
            report.add("G5-semantic", f"Orphan result: {sid} has no subject (attempt {result.get('attemptId')}).")
        if aid not in assessment_ids:
            report.add("G5-semantic", f"Broken assessment reference: {result.get('attemptId')} -> {aid}.")
        status = result.get("status")
        if status not in ALLOWED_STATUSES:
            report.add("G5-semantic", f"Disallowed result status: {status!r} (attempt {result.get('attemptId')}).")
        if result.get("studentId") is None or result.get("assessmentId") is None:
            report.add("G5-semantic", "Result with missing studentId/assessmentId.")

    publication_id = manifest.get("publicationId")
    supersedes = manifest.get("supersedesPublicationId")
    corrects = manifest.get("correctsPublicationId")
    if supersedes and corrects:
        report.add("G5-semantic", "supersedesPublicationId and correctsPublicationId are mutually exclusive.")
    for rel_id in (supersedes, corrects):
        if rel_id == publication_id:
            report.add("G5-semantic", "A publication cannot reference itself via correction/supersession.")
    if supersedes and not supersedes.startswith("pub_"):
        report.add("G5-semantic", f"Invalid supersedesPublicationId: {supersedes}")
    if corrects and not corrects.startswith("pub_"):
        report.add("G5-semantic", f"Invalid correctsPublicationId: {corrects}")


def _iter_abs_path_values(payload) -> list[str]:
    """All string values that contain absolute paths or file URLs (POSIX/Windows)."""
    values: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            values.extend(_iter_abs_path_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_abs_path_values(item))
    elif isinstance(payload, str):
        if (
            _RE_POSIX_ABS.search(payload)
            or _RE_WINDOWS_ABS.search(payload)
            or _RE_UNC_ABS.search(payload)
            or _RE_FILE_URL.search(payload)
        ):
            values.append(payload)
    return values


def _detect_known_names(text: str, known_names: set[str]) -> list[str]:
    """Roster names appearing as whole words inside free text (feedback/components).

    Guards against student identity leaking into reviewed content when no
    sanitization policy exists yet (P0 privacy, items 26-27). Only names of at
    least 4 characters are considered to avoid matching short common words.
    """
    if not text or not known_names:
        return []
    found = set()
    for name in known_names:
        for token in name.split():
            if len(token) < 4:
                continue
            if re.search(rf"(?<![A-Za-zÁÉÍÓÚáéíóúÑñ]){re.escape(token)}(?![A-Za-zÁÉÍÓÚáéíóúÑñ])", text):
                found.add(name)
    return sorted(found)


def gate_privacy(report: VerifyReport, root: Path, files: dict[str, Path], known_names: Optional[set[str]] = None) -> None:
    """G6 — no PII, no secrets, no absolute paths, no forbidden keys, no roster names in content."""
    try:
        from c0.scanner import Scanner

        scanner = Scanner(allowlist=[])
    except Exception:
        scanner = None

    for rel, path in files.items():
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            report.add("G6-privacy", f"Unreadable file: {rel}")
            continue
        if _contains_pii(content):
            report.add("G6-privacy", f"RUT or email pattern detected in {rel}.")
        if scanner is not None:
            findings = scanner.scan_blob(rel, content.encode("utf-8"))
            for finding in findings:
                report.add("G6-privacy", f"{rel}: {finding.severity} {finding.rule}: {finding.message}")

        payload = _json_payload(path)
        if payload is not None:
            for value in _iter_abs_path_values(payload):
                report.add("G6-privacy", f"Absolute path or file URL in {rel}: {value!r}")

        if rel.startswith(CANONICAL_PREFIX):
            if payload is not None:
                keys = list(_iter_keys(payload))
                forbidden = sorted(set(keys) & PII_KEYS)
                if forbidden:
                    report.add("G6-privacy", f"Forbidden keys in {rel}: {forbidden}")

            if known_names and rel == "canonical/results.json":
                hits = _detect_known_names(content, known_names)
                if hits:
                    report.add(
                        "G6-privacy",
                        f"{len(hits)} known roster name(s) detected in free text of {rel} "
                        "(sanitization policy required).",
                    )


def gate_manifest(report: VerifyReport, root: Path, files: dict[str, Path]) -> None:
    """G7 — declared files exist, sizes/hashes correct, contentHash/reviewHash reproducible."""
    manifest_path = root / "manifest.json"
    manifest = _json_payload(manifest_path)
    if manifest is None:
        report.add("G7-manifest", "manifest.json missing or invalid.")
        return

    declared = manifest.get("files", {})
    if not isinstance(declared, dict):
        report.add("G7-manifest", "manifest.files is not an object.")
        return

    for rel, entry in declared.items():
        path = root / rel
        if not path.is_file():
            report.add("G7-manifest", f"Declared file missing: {rel}")
            continue
        actual_size = path.stat().st_size
        expected_size = entry.get("size")
        if expected_size is not None and actual_size != expected_size:
            report.add("G7-manifest", f"Size mismatch for {rel}: got {actual_size}, expected {expected_size}.")
        actual_hash = sha256_file(path)
        expected_hash = entry.get("sha256")
        if expected_hash is not None and actual_hash != expected_hash:
            report.add("G7-manifest", f"Hash mismatch for {rel}.")

    extra = sorted(set(files) - set(declared) - {"manifest.json"})
    if extra:
        report.add("G7-manifest", f"Extra file(s) not declared: {extra}")

    content_hashes = {}
    for rel, path in files.items():
        if is_content_file(rel):
            content_hashes[rel] = sha256_file(path)
    expected = manifest.get("contentHash")
    computed = compute_content_hash(content_hashes)
    if expected is None:
        report.add("G7-manifest", "manifest.contentHash is missing.")
    elif computed != expected:
        report.add("G7-manifest", f"contentHash mismatch: got {computed}, expected {expected}.")

    core = {
        "sectionId": manifest.get("sectionId"),
        "publicationId": manifest.get("publicationId"),
        "supersedesPublicationId": manifest.get("supersedesPublicationId"),
        "correctsPublicationId": manifest.get("correctsPublicationId"),
        "engineVersion": manifest.get("engineVersion"),
        "adapterVersion": manifest.get("adapterVersion"),
        "policySnapshotVersion": manifest.get("policySnapshotVersion"),
    }
    required_core = (
        core["sectionId"],
        core["publicationId"],
        core["engineVersion"],
        core["adapterVersion"],
        core["policySnapshotVersion"],
    )
    if not all(required_core):
        report.add("G7-manifest", "manifest is missing immutable core fields for the review hash.")
        return
    entries = {}
    for rel, entry in content_file_entries(declared).items():
        path = root / rel
        if not path.is_file():
            continue
        entries[rel] = {
            "sha256": sha256_file(path),
            "classification": entry.get("classification"),
            "audience": entry.get("audience"),
        }
    computed_review = review_hash(computed, core, entries)
    expected_review = manifest.get("reviewHash")
    if expected_review is None:
        report.add("G7-manifest", "manifest.reviewHash is missing.")
    elif computed_review != expected_review:
        report.add(
            "G7-manifest",
            f"reviewHash mismatch: got {computed_review}, expected {expected_review}.",
        )

    cross_checks = [
        (root / "approvals" / "review.json", "review"),
        (root / "approvals" / "publication-approval.json", "publication-approval"),
    ]
    for path, label in cross_checks:
        if not path.is_file():
            continue
        doc = _json_payload(path)
        if doc is None:
            report.add("G8-lifecycle", f"{label}.json is not a valid JSON object.")
            continue
        if doc.get("publicationId") != manifest.get("publicationId"):
            report.add("G8-lifecycle", f"{label} references a different publicationId.")
        if doc.get("contentHash") != manifest.get("contentHash"):
            report.add("G8-lifecycle", f"{label}.contentHash does not match manifest.contentHash.")
        if doc.get("reviewHash") != manifest.get("reviewHash"):
            report.add("G8-lifecycle", f"{label}.reviewHash does not match manifest.reviewHash.")


def gate_classification(report: VerifyReport, root: Path, files: dict[str, Path]) -> None:
    """G9 — every declared file carries the expected classification and audience."""
    manifest = _json_payload(root / "manifest.json")
    if manifest is None:
        return
    declared = manifest.get("files", {})
    if not isinstance(declared, dict):
        return
    for rel, entry in declared.items():
        expected = expected_file_meta(rel)
        if expected is None:
            report.add("G9-classification", f"Unexpected file path with no classification: {rel}")
            continue
        expected_class, expected_audience = expected
        if entry.get("classification") != expected_class or entry.get("audience") != expected_audience:
            report.add(
                "G9-classification",
                f"{rel}: expected {expected_class}/{expected_audience}, "
                f"got {entry.get('classification')}/{entry.get('audience')}.",
            )


def gate_lifecycle(report: VerifyReport, root: Path, files: dict[str, Path], immutable: bool = False) -> None:
    """G8 — status/approval consistency and immutability of approved snapshots.

    ``immutable`` must be True only when the snapshot is already promoted and made
    read-only; staging drafts that carry an approved-status manifest (during the
    approval write) are verified with ``immutable=False``.
    """
    manifest = _json_payload(root / "manifest.json")
    if manifest is None:
        return
    status = manifest.get("status")
    has_review = (root / "approvals" / "review.json").is_file()
    has_approval = (root / "approvals" / "publication-approval.json").is_file()

    if status == "approved" and not has_approval:
        report.add("G8-lifecycle", "Approved snapshot is missing publication-approval.json.")
    if status == "reviewed" and not has_review:
        report.add("G8-lifecycle", "Reviewed snapshot is missing review.json.")
    if status in ("draft",) and has_approval:
        report.add("G8-lifecycle", "Draft snapshot unexpectedly contains publication-approval.json.")

    if status == "approved" and immutable:
        for rel, path in files.items():
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o222:
                report.add("G8-lifecycle", f"Approved snapshot file is writable: {rel}")


GATE_RUNNERS = (
    gate_contract,
    gate_semantic,
    gate_privacy,
    gate_manifest,
    gate_classification,
)


def verify_snapshot(
    root: Path,
    section_id: Optional[str] = None,
    publication_id: Optional[str] = None,
    immutable: bool = False,
    known_names: Optional[set[str]] = None,
) -> VerifyReport:
    """Verify a snapshot directory (staging draft or approved). Read-only.

    ``known_names`` supplies the legacy roster names used to detect student
    identity leaking into free text (feedback/components).
    """
    root = Path(root)
    report = VerifyReport(root=root)
    files = _walk_files(root)
    if not files:
        report.add("G0-boundary", "Snapshot directory is empty or missing.")
        return report

    manifest = _json_payload(root / "manifest.json")
    if section_id is not None:
        if manifest is None or manifest.get("sectionId") != section_id:
            report.add("G5-semantic", f"manifest.sectionId does not match {section_id!r}.")
    if publication_id is not None:
        if manifest is None or manifest.get("publicationId") != publication_id:
            report.add("G5-semantic", f"manifest.publicationId does not match {publication_id!r}.")

    for runner in GATE_RUNNERS:
        if runner is gate_privacy:
            runner(report, root, files, known_names=known_names)
        else:
            runner(report, root, files)
    gate_lifecycle(report, root, files, immutable=immutable)
    return report
