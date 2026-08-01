"""Compatibility views generated from approved snapshots (C1).

Views are envelopes that declare their provenance (``sourcePublicationId``,
``canonicalSourceHash``, ``generatedAt``) and embed the actual content under
``content``. They are derived artifacts: they never mutate the approved
snapshot and are produced only from an approved publication. Legacy aliases
(course/*, evaluations.json, grades.json) require an explicit
``update_legacy_aliases`` flag and live in the compat namespace, never in the
global ``exports/`` tree (invariant 9: new components do not depend on the
global legacy path).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .clock import Clock
from .errors import PublicationError
from .jsonutil import read_json, write_json
from .schemas import SCHEMA_VERSION, validate_compatibility_view
from .verify import VerifyReport, gate_privacy

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


def _course_results(results: list[dict]) -> list[dict]:
    """Legacy-shaped results rows (opaque ids, preserved statuses/feedback)."""
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
    """Pure, deterministic view content derived from the canonical payloads."""
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


def generate(
    ctx,
    *,
    update_legacy_aliases: bool = False,
    out_dir: Optional[Path] = None,
) -> list[str]:
    """Generate compatibility views from the approved snapshot for this context.

    Returns the list of written relative paths. Fails closed if the snapshot is
    not approved or if any generated view violates the envelope contract.
    """
    dest = ctx.destination_dir()
    if not dest.is_dir():
        raise PublicationError(f"No approved snapshot at {dest}; run build/review/approve first.")
    manifest = read_json(dest / "manifest.json")
    if manifest.get("status") != "approved":
        raise PublicationError(
            f"Compatibility views require an approved snapshot (status={manifest.get('status')!r})."
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

    written: list[Path] = []
    for rel, envelope in envelopes.items():
        path = (out_dir or _view_root(ctx)) / rel
        write_json(path, envelope)
        written.append(path)

    if update_legacy_aliases:
        alias_root = legacy_alias_dir(ctx, ctx.section_id)
        for rel, envelope in envelopes.items():
            write_json(alias_root / rel, envelope)

    report = VerifyReport(root=Path())
    files = {path.relative_to(_view_root(ctx)).as_posix(): path for path in written}
    gate_privacy(report, _view_root(ctx), files)
    content_findings = _content_findings(report)
    if content_findings:
        raise PublicationError(
            "Compatibility views contain PII or unsafe patterns: "
            + "; ".join(content_findings)
        )
    return sorted(set(envelopes) | ({"legacy/" + rel for rel in envelopes} if update_legacy_aliases else set()))


def _view_root(ctx) -> Path:
    return section_compat_dir(ctx, ctx.section_id) / ctx.publication_id
