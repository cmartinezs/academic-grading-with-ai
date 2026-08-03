"""Deterministic StudentPortalView projection builder (pure, no I/O).

The projection consumes only canonical snapshot payloads plus optional identity
inputs supplied by the caller. It never reads configuration, filesystem state,
or the roster on its own.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .canonical import compute_hash
from .models import PORTAL_VIEW_SCHEMA_VERSION, STUDENT_ID_RE, validate_section_id
from .errors import ValidationError
from .snapshot import read_canonical

GENERATED_FROM = "student-portal/projection/v1"


def decimal_str(value) -> Optional[str]:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _assessment_label(assessments_index: dict, assessment_id: str) -> str:
    entry = assessments_index.get(assessment_id) or {}
    title = entry.get("title")
    if not isinstance(title, str) or not title:
        return assessment_id
    return title


def _assessment_unit(assessments_index: dict, assessment_id: str) -> Optional[str]:
    entry = assessments_index.get(assessment_id) or {}
    unit = entry.get("unit")
    return unit if isinstance(unit, str) and unit else None


def _result_assessments(results: list, assessments_index: dict) -> list:
    items = []
    for result in results:
        assessment_id = result.get("assessmentId")
        if not isinstance(assessment_id, str) or not assessment_id:
            continue
        items.append(
            {
                "assessmentId": assessment_id,
                "label": _assessment_label(assessments_index, assessment_id),
                "status": result.get("status"),
                "score": decimal_str(result.get("score")),
                "grade": decimal_str(result.get("grade")),
                "unit": _assessment_unit(assessments_index, assessment_id),
                "feedback": result.get("feedback"),
            }
        )
    items.sort(key=lambda item: item["assessmentId"])
    return items


def build_legacy_projection(
    section_id: str,
    publication_id: str,
    student_id: str,
    subjects: list,
    results: list,
    assessments: list,
) -> dict:
    if not STUDENT_ID_RE.match(student_id):
        raise ValidationError(f"Invalid studentId: {student_id!r}")
    assessments_index = {a.get("assessmentId"): a for a in assessments}
    student_results = [r for r in results if r.get("studentId") == student_id]
    return {
        "schemaVersion": PORTAL_VIEW_SCHEMA_VERSION,
        "sectionId": section_id,
        "publicationId": publication_id,
        "studentId": student_id,
        "snapshotMode": "legacy-effective",
        "assessments": _result_assessments(student_results, assessments_index),
        "finalOutcome": None,
        "generatedFrom": GENERATED_FROM,
    }


def _subject_outcome(outcomes: list, student_id: str) -> Optional[dict]:
    for outcome in outcomes:
        if outcome.get("subjectId") == student_id:
            return outcome
    return None


def build_c2_projection(
    section_id: str,
    publication_id: str,
    student_id: str,
    subjects: list,
    results: list,
    assessments: list,
    outcomes: list,
) -> dict:
    if not STUDENT_ID_RE.match(student_id):
        raise ValidationError(f"Invalid studentId: {student_id!r}")
    assessments_index = {a.get("assessmentId"): a for a in assessments}
    student_results = [r for r in results if r.get("studentId") == student_id]
    outcome = _subject_outcome(outcomes, student_id)
    final_outcome = None
    if outcome is not None:
        value = outcome.get("value")
        final_outcome = {
            "value": decimal_str(value.get("value")) if value else None,
            "unit": (value or {}).get("unit") if value else None,
            "resultState": outcome.get("resultState"),
            "finalizable": outcome.get("finalizable"),
        }
    return {
        "schemaVersion": PORTAL_VIEW_SCHEMA_VERSION,
        "sectionId": section_id,
        "publicationId": publication_id,
        "studentId": student_id,
        "snapshotMode": "grade-policy-effective",
        "assessments": _result_assessments(student_results, assessments_index),
        "finalOutcome": final_outcome,
        "generatedFrom": GENERATED_FROM,
    }


def build_projection(
    section_id: str,
    publication_id: str,
    snapshot_dir,
    student_id: str,
    snapshot_mode: str,
) -> dict:
    """Build a StudentPortalView for one student from snapshot canonical files."""
    validate_section_id(section_id)
    subjects_doc = read_canonical(snapshot_dir, "canonical/subjects.json")
    results_doc = read_canonical(snapshot_dir, "canonical/results.json")
    assessments_doc = read_canonical(snapshot_dir, "canonical/assessments.json")
    subjects = subjects_doc.get("subjects", [])
    results = results_doc.get("results", [])
    assessments = assessments_doc.get("assessments", [])

    if snapshot_mode == "legacy-effective":
        return build_legacy_projection(
            section_id, publication_id, student_id, subjects, results, assessments
        )
    if snapshot_mode == "grade-policy-effective":
        outcomes_doc = read_canonical(snapshot_dir, "canonical/outcomes.json")
        outcomes = outcomes_doc.get("subjectOutcomes", [])
        return build_c2_projection(
            section_id, publication_id, student_id, subjects, results, assessments, outcomes
        )
    raise ValidationError(f"Unsupported snapshot mode: {snapshot_mode!r}")


def subject_student_ids(snapshot_dir) -> list:
    subjects_doc = read_canonical(snapshot_dir, "canonical/subjects.json")
    return [s.get("studentId") for s in subjects_doc.get("subjects", []) if s.get("studentId")]


def projection_hash(view: dict) -> str:
    return compute_hash(view)
