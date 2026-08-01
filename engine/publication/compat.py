"""Compatibility views generated from approved snapshots (C1).

Two kinds of derived artifacts are produced, never mutating the approved
snapshot and only from an approved publication:

- **versioned compatibility views**: envelopes that declare their provenance
  (``sourcePublicationId``, ``canonicalSourceHash``, ``generatedAt``) and embed
  the content under ``content`` (C1 contract);
- **legacy aliases**: exact legacy-contract payloads (``course/*`` with
  ``{"items": [...]}`` wrappers and the contractual result keys) carrying
  provenance in a sidecar ``legacy/PROVENANCE.json``.

Generation runs entirely under the per-(section, publication) lock: the
approved snapshot and the lifecycle are re-validated inside the lock, staging
is unique per operation, and both the versioned views and the alias bundle are
promoted atomically. A failure never leaves partial files at the destination,
and staging belonging to another execution is never deleted.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from .builder import _fsync_tree, check_same_filesystem
from .clock import Clock
from .errors import DestinationExistsError, PublicationError
from .jsonutil import read_json, write_json
from .lifecycle import TERMINAL_EVENTS
from .locking import publication_lock
from .schemas import SCHEMA_VERSION, validate_compatibility_view
from .verify import VerifyReport, gate_privacy, verify_snapshot

GENERATED_BY = "publication-snapshot/compat/v1"

COMPAT_REL = "compat"
LEGACY_ALIAS_REL = "legacy"

# Path-layout rules from the C0 scanner that do not apply to the derived compat
# namespace (filenames intentionally mirror the legacy export: grades.json,
# students.json, course/...). Content rules (RUT, email, secrets) still apply.
_PATH_ONLY_RULES = frozenset(
    {
        "submissions-dir",
        "results-dir",
        "roster-file",
        "operational-state",
        "email-preview-log",
        "env-file",
        "private-key-file",
    }
)

# gate_privacy formats content findings as "<severity> <rule>: <message>".
_RE_RULE = re.compile(r"\b(?:BLOCK|REVIEW|INFO)\s+([a-z0-9-]+):")



def _content_findings(report) -> list[str]:
    messages = []
    for finding in report.findings:
        if finding.gate != "G6-privacy":
            continue
        match = _RE_RULE.search(finding.message)
        if match and match.group(1) in _PATH_ONLY_RULES:
            continue
        messages.append(finding.message)
    return messages


def compat_root(ctx) -> Path:
    return ctx.runtime.publications_root / COMPAT_REL


def section_compat_dir(ctx, section_id: str) -> Path:
    return compat_root(ctx) / section_id


def legacy_alias_dir(ctx, section_id: str) -> Path:
    return section_compat_dir(ctx, section_id) / LEGACY_ALIAS_REL


def _operation_id() -> str:
    return uuid.uuid4().hex[:16]


def _unique_staging(base: Path, section_id: str, publication_id: str, operation_id: str) -> Path:
    return base / section_id / publication_id / operation_id


def _fsync_parent(parent: Path) -> None:
    try:
        fd = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Versioned compatibility views (C1 envelope contract)
# ---------------------------------------------------------------------------


def _course_results(results: list[dict]) -> list[dict]:
    """Versioned-view results rows (opaque ids, preserved statuses/feedback)."""
    rows = []
    for result in results.get("results", []):
        rows.append(
            {
                "studentId": result.get("studentId"),
                "assessmentId": result.get("assessmentId"),
                "attemptId": result.get("attemptId"),
                "status": result.get("status"),
                "score": result.get("score"),
                "grade": result.get("grade"),
                "feedback": result.get("feedback"),
            }
        )
    return rows


def build_views(canonical: dict[str, dict]) -> dict[str, dict]:
    """Pure, deterministic versioned-view content derived from canonical payloads."""
    section = canonical["section"]
    subjects = canonical["subjects"]
    assessments = canonical["assessments"]
    results = canonical["results"]

    evaluations = [
        {
            "assessmentId": item["assessmentId"],
            "title": item.get("title"),
            "type": item.get("type"),
            "date": item.get("date"),
            "forms": item.get("forms") or [],
        }
        for item in assessments.get("assessments", [])
    ]
    grades = [
        {
            "studentId": item.get("studentId"),
            "assessmentId": item.get("assessmentId"),
            "attemptId": item.get("attemptId"),
            "status": item.get("status"),
            "score": item.get("score"),
            "grade": item.get("grade"),
        }
        for item in results.get("results", [])
    ]
    course_results = _course_results(results)

    status_counts: dict[str, int] = {}
    for item in results.get("results", []):
        status = item.get("status") or "Pendiente"
        status_counts[status] = status_counts.get(status, 0) + 1

    course = section.get("course") or {}
    return {
        "evaluations.json": {"evaluations": evaluations},
        "grades.json": {"grades": grades},
        "course/course.json": {
            "code": course.get("code"),
            "title": course.get("title"),
            "term": section.get("term"),
        },
        "course/students.json": {
            "students": [
                {"studentId": item["studentId"], "academicState": item.get("academicState")}
                for item in subjects.get("subjects", [])
            ]
        },
        "course/evaluations.json": {"evaluations": evaluations},
        "course/results.json": {"results": course_results},
        "course/course-summary.json": {
            "studentCount": len(subjects.get("subjects", [])),
            "assessmentCount": len(assessments.get("assessments", [])),
            "evaluatedAttempts": len(course_results),
            "statusCounts": status_counts,
        },
    }


# ---------------------------------------------------------------------------
# Exact legacy alias payloads
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate(
    ctx,
    *,
    update_legacy_aliases: bool = False,
    out_dir: Optional[Path] = None,
) -> list[str]:
    """Generate compatibility views from the approved snapshot for this context.

    The whole operation runs under the per-publication lock: the approved
    snapshot and the lifecycle are re-validated inside the lock, staging is
    unique per operation (``<operationId>``) and only own staging is ever
    removed. The versioned destination rejects overwrites; legacy aliases
    require an explicit ``update_legacy_aliases`` flag.
    """
    with publication_lock(ctx.runtime.state_root, ctx.section_id, ctx.publication_id):
        written = _generate_locked(
            ctx,
            update_legacy_aliases=update_legacy_aliases,
            out_dir=out_dir,
        )
    return sorted(set(written))


def _generate_locked(
    ctx,
    *,
    update_legacy_aliases: bool,
    out_dir: Optional[Path],
) -> list[str]:
    dest = ctx.destination_dir()
    if not dest.is_dir():
        raise PublicationError(f"No approved snapshot for publication {ctx.publication_id}.")
    manifest = read_json(dest / "manifest.json")
    if manifest.get("status") != "approved":
        raise PublicationError(
            f"Compatibility views require an approved snapshot (status={manifest.get('status')!r})."
        )
    report = verify_snapshot(dest, ctx.section_id, ctx.publication_id, immutable=True)
    if not report.passed():
        raise PublicationError(
            "Approved snapshot fails verification; refusing to generate views. "
            + "; ".join(f.message for f in report.findings)
        )
    state = ctx.ledger().current_state(ctx.publication_id)
    if state in TERMINAL_EVENTS:
        raise PublicationError(
            f"Cannot generate compatibility views from a {state} snapshot."
        )

    canonical = {
        "section": read_json(dest / "canonical/section.json"),
        "subjects": read_json(dest / "canonical/subjects.json"),
        "assessments": read_json(dest / "canonical/assessments.json"),
        "results": read_json(dest / "canonical/results.json"),
        "policy": read_json(dest / "canonical/policy.json"),
    }

    content = build_views(canonical)
    envelopes: dict[str, dict] = {}
    for rel, view_content in content.items():
        envelope = {
            "schemaVersion": SCHEMA_VERSION,
            "sourcePublicationId": ctx.publication_id,
            "generatedBy": GENERATED_BY,
            "canonicalSourceHash": manifest["contentHash"],
            "generatedAt": ctx.clock.iso(),
            "content": view_content,
        }
        errors = validate_compatibility_view(envelope)
        if errors:
            raise PublicationError(f"Compatibility view failed validation ({rel}): {errors}")
        envelopes[rel] = envelope

    operation_id = _operation_id()
    staging = _unique_staging(
        ctx.runtime.temp_root / "compat-staging", ctx.section_id, ctx.publication_id, operation_id
    )
    staging.mkdir(parents=True)
    try:
        for rel, envelope in envelopes.items():
            write_json(staging / rel, envelope)

        report = VerifyReport(root=staging)
        files = {rel: staging / rel for rel in envelopes}
        gate_privacy(report, staging, files)
        content_findings = _content_findings(report)
        if content_findings:
            raise PublicationError(
                "Compatibility views contain PII or unsafe patterns: "
                + "; ".join(content_findings)
            )

        _hash_gate(staging, envelopes, manifest)

        _fsync_tree(staging)

        target = Path(out_dir) if out_dir is not None else _view_root(ctx)
        if target.exists():
            raise DestinationExistsError(
                f"Compatibility views already exist for publication {ctx.publication_id}."
            )
        check_same_filesystem(staging, target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, target)
        _fsync_parent(target.parent)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    written = [rel for rel in envelopes]
    if update_legacy_aliases:
        written.extend(_commit_legacy_aliases(ctx, content, manifest))
    return sorted(set(written))


def _hash_gate(staging: Path, envelopes: dict[str, dict], manifest: dict) -> None:
    """Every staged envelope must match the source manifest content hash."""
    problems = []
    for rel, envelope in envelopes.items():
        path = staging / rel
        if not path.is_file():
            problems.append(f"{rel}: missing from staging")
            continue
        on_disk = read_json(path)
        if on_disk.get("canonicalSourceHash") != manifest.get("contentHash"):
            problems.append(f"{rel}: canonicalSourceHash does not match the source contentHash")
    if problems:
        raise PublicationError("Compatibility staging failed the manifest/hash gate: " + "; ".join(problems))


def _commit_legacy_aliases(ctx, content: dict[str, dict], manifest: dict) -> list[str]:
    """Update the legacy aliases + provenance sidecar from staged view content.

    Alias files carry the bare view content (no envelope wrapper) so legacy
    consumers are unaffected; provenance lives in a sidecar ``PROVENANCE.json``.
    Staging is unique per operation and only own staging is removed.
    """
    alias_root = legacy_alias_dir(ctx, ctx.section_id)
    operation_id = _operation_id()
    staging = _unique_staging(
        ctx.runtime.temp_root / "compat-alias-staging", ctx.section_id, ctx.publication_id, operation_id
    )
    staging.mkdir(parents=True)
    try:
        for rel, view_content in content.items():
            write_json(staging / rel, view_content)
        write_json(
            staging / "PROVENANCE.json",
            {
                "schemaVersion": SCHEMA_VERSION,
                "generatedBy": GENERATED_BY,
                "sourcePublicationId": ctx.publication_id,
                "canonicalSourceHash": manifest["contentHash"],
                "generatedAt": ctx.clock.iso(),
            },
        )

        report = VerifyReport(root=staging)
        files = {
            path.relative_to(staging).as_posix(): path
            for path in staging.rglob("*")
            if path.is_file()
        }
        gate_privacy(report, staging, files)
        content_findings = _content_findings(report)
        if content_findings:
            raise PublicationError(
                "Legacy aliases contain PII or unsafe patterns: "
                + "; ".join(content_findings)
            )

        _fsync_tree(staging)

        alias_root.mkdir(parents=True, exist_ok=True)
        written = []
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(staging).as_posix()
            write_json(alias_root / rel, read_json(path))
            written.append(f"legacy/{rel}")
        return written
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _view_root(ctx) -> Path:
    return section_compat_dir(ctx, ctx.section_id) / ctx.publication_id
