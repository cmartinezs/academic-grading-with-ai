"""C2 <-> publication snapshot integration.

Turns a validated grade policy plus the canonical snapshot data
(subjects/assessments/results) into the three C2 canonical payloads:

- ``canonical/policy.json``        (mode ``grade-policy-effective``)
- ``canonical/outcomes.json``      (stable result surface)
- ``canonical/traces.json``        (per-stage audit trail)

The integration is deterministic: same canonical data + policy file always
yields the same three documents, so ``contentHash``/``reviewHash`` are stable
across rebuilds.

Snapshot mode is the authority boundary between ``canonical/results.json`` and
the grade policy engine, and it is fail-closed:

- every assessment the policy reads must declare its unit in ``assessmentUnits``
  (``canonical/results.json`` carries no unit, so the engine never guesses one);
- more than one result for the same ``(studentId, assessmentId)`` is rejected
  (C2 V1 has no attempt-selection policy; array order is never a selection
  policy);
- an unparseable or non-finite score is a typed data error, never converted
  into a missing policy;
- the canonical payloads must satisfy the C1 structural contract (schemaVersion,
  sectionId, opaque studentId/attemptId, status, components, score) before any
  calculation runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Optional

from decimal import InvalidOperation

from .decimal import Decimal, to_decimal
from .errors import (
    CanonicalFormatError,
    DuplicateAttemptError,
    GradePolicyError,
    InvalidScoreError,
    SchemaValidationError,
    SemanticValidationError,
    UsageError,
)
from .models import AcademicValue, AssessmentInput, NormalizedInputs
from .trace import outcomes_document, policy_hash, traces_document
from .validator import load_policy
from .version import __version__

OUTCOMES_REL = "canonical/outcomes.json"
TRACES_REL = "canonical/traces.json"
POLICY_REL = "canonical/policy.json"

_STUDENT_ID_RE = re.compile(r"^stu_[A-Za-z0-9]{1,64}$")
_ATTEMPT_ID_RE = re.compile(r"^att_[A-Za-z0-9]{1,64}$")

_RESULT_REQUIRED = ("studentId", "assessmentId", "attemptId", "status", "components")


def load_policy_document(source: Path) -> dict:
    """Load a policy file from disk (fail-closed on I/O/JSON errors)."""
    try:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UsageError(f"Grade policy file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"Grade policy file is not valid JSON: {source}") from exc
    if not isinstance(raw, dict):
        raise SchemaValidationError("Grade policy document must be a JSON object.")
    return raw


def build_effective_policy(section_id: str, policy) -> dict:
    """The grade-policy-effective canonical/policy.json payload."""
    return {
        "schemaVersion": "1.0.0",
        "policySchemaVersion": policy.schema_version,
        "mode": "grade-policy-effective",
        "calculationAuthority": "grade-policy-engine",
        "policyId": policy.policy_id,
        "policyVersion": policy.policy_version,
        "engineVersion": __version__,
        "policyHash": policy_hash(policy.raw),
        "policy": policy.raw,
    }


def _require_payload(
    canonical: Mapping[str, object],
    rel: str,
    collection_key: str,
    *,
    required_headers: tuple[str, ...],
) -> tuple[dict, list[dict]]:
    """Return the payload and its item list, enforcing the C1 structural shape.

    Raises ``CanonicalFormatError`` (typed, no PII, no private paths) when the
    payload is missing, has the wrong shape or lacks the required headers.
    """
    payload = canonical.get(rel)
    if not isinstance(payload, dict):
        raise CanonicalFormatError(
            f"canonical {rel}: missing or non-object payload; C2 snapshot mode "
            "requires the C1 canonical payload."
        )
    for header in required_headers:
        if header not in payload:
            raise CanonicalFormatError(
                f"canonical {rel}: required header {header!r} is missing "
                "(C1 schema)."
            )
    items = payload.get(collection_key)
    if not isinstance(items, list):
        raise CanonicalFormatError(
            f"canonical {rel}: {collection_key!r} must be an array."
        )
    for item in items:
        if not isinstance(item, dict):
            raise CanonicalFormatError(
                f"canonical {rel}: every item in {collection_key!r} must be an object."
            )
    return payload, items


def _check_canonical_precondition(canonical: Mapping[str, object]) -> None:
    """Fail-closed precondition on the canonical payloads the engine reads.

    ``build_c2_payloads`` is never exercised against incomplete structures:
    results must satisfy the C1 contract (opaque studentId/attemptId, status,
    components and score) before any calculation runs.
    """
    _, subjects = _require_payload(
        canonical,
        "canonical/subjects.json",
        "subjects",
        required_headers=("schemaVersion", "sectionId"),
    )
    for item in subjects:
        if not isinstance(item.get("studentId"), str) or not _STUDENT_ID_RE.match(item["studentId"]):
            raise CanonicalFormatError(
                "canonical/subjects.json: studentId must be an opaque stu_ id."
            )

    _, assessments = _require_payload(
        canonical,
        "canonical/assessments.json",
        "assessments",
        required_headers=("schemaVersion", "sectionId"),
    )
    for item in assessments:
        if not isinstance(item.get("assessmentId"), str) or not item["assessmentId"]:
            raise CanonicalFormatError(
                "canonical/assessments.json: assessmentId is required."
            )

    _, results = _require_payload(
        canonical,
        "canonical/results.json",
        "results",
        required_headers=("schemaVersion", "sectionId"),
    )
    for item in results:
        for field in _RESULT_REQUIRED:
            if field not in item:
                raise CanonicalFormatError(
                    f"canonical/results.json: result item is missing {field!r}."
                )
        if not isinstance(item["studentId"], str) or not _STUDENT_ID_RE.match(item["studentId"]):
            raise CanonicalFormatError(
                "canonical/results.json: studentId must be an opaque stu_ id."
            )
        if not isinstance(item["attemptId"], str) or not _ATTEMPT_ID_RE.match(item["attemptId"]):
            raise CanonicalFormatError(
                "canonical/results.json: attemptId must be an opaque att_ id."
            )
        if not isinstance(item["assessmentId"], str) or not item["assessmentId"]:
            raise CanonicalFormatError(
                "canonical/results.json: assessmentId is required."
            )
        if not isinstance(item["components"], list):
            raise CanonicalFormatError(
                "canonical/results.json: components must be an array."
            )
        score = item.get("score")
        if score is not None and not isinstance(score, (int, float, str)):
            raise CanonicalFormatError(
                "canonical/results.json: score must be a number, a string or null."
            )


def _assessment_index(canonical: Mapping[str, object]) -> dict[str, dict]:
    assessments = canonical.get("canonical/assessments.json", {})
    payload = assessments if isinstance(assessments, dict) else {}
    items = payload.get("assessments") or []
    return {
        str(item.get("assessmentId")): item
        for item in items
        if isinstance(item, dict) and item.get("assessmentId")
    }


def _subjects_index(canonical: Mapping[str, object]) -> dict[str, dict]:
    subjects = canonical.get("canonical/subjects.json", {})
    payload = subjects if isinstance(subjects, dict) else {}
    items = payload.get("subjects") or []
    return {
        str(item.get("studentId")): item
        for item in items
        if isinstance(item, dict) and item.get("studentId")
    }


def _results_for(canonical: Mapping[str, object]) -> dict[tuple[str, str], dict]:
    """Index canonical results by ``(studentId, assessmentId)``.

    Rejects any ``(studentId, assessmentId)`` that appears more than once: C2 V1
    has no attempt-selection policy, so array order is never used as a selection
    rule (no implicit first/last/best).
    """
    results = canonical.get("canonical/results.json", {})
    payload = results if isinstance(results, dict) else {}
    index: dict[tuple[str, str], dict] = {}
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("studentId") or "")
        aid = str(item.get("assessmentId") or "")
        if not sid or not aid:
            continue
        key = (sid, aid)
        if key in index:
            raise DuplicateAttemptError(
                f"duplicate canonical result for (studentId, assessmentId) = "
                f"({sid}, {aid}); C2 V1 rejects multiple attempts for the same "
                "assessment — selecting an attempt would need an explicit policy "
                "(first/last/best are not implicit rules)."
            )
        index[key] = item
    return index


def _to_score(ref: str, value, unit: str) -> Optional[AcademicValue]:
    """Convert a canonical score to a typed value, or None for a missing score.

    - ``null``/empty -> ``None`` (missing input, governed by the stage policy);
    - valid scalar -> ``Decimal`` (finite, non-NaN/non-Infinity);
    - anything else -> ``InvalidScoreError`` (a data error, never a missing
      policy; the message carries the assessment id but never the raw value, so
      no email/RUT/name leaks through).
    """
    if value is None or value == "":
        return None
    try:
        decimal_value = to_decimal(value)
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise InvalidScoreError(
            f"canonical result for assessment {ref!r}: score is not a finite "
            "number (expected a number, a decimal string or null)."
        ) from exc
    if not decimal_value.is_finite():
        raise InvalidScoreError(
            f"canonical result for assessment {ref!r}: score is not finite "
            "(NaN/Infinity are rejected)."
        )
    return AcademicValue(decimal_value, unit)


def build_c2_payloads(
    section_id: str,
    canonical: Mapping[str, object],
    policy_document: dict,
) -> dict[str, dict]:
    """Compute the three C2 canonical payloads from canonical data + policy.

    Raises ``GradePolicyError`` subclasses on any failure; callers must not
    write a partial snapshot when this raises.
    """
    policy = load_policy(policy_document)
    _check_canonical_precondition(canonical)

    assessment_index = _assessment_index(canonical)
    subjects_index = _subjects_index(canonical)
    results_index = _results_for(canonical)

    for ref in policy.assessments:
        if ref not in assessment_index:
            from .errors import StageReferenceError

            raise StageReferenceError(
                f"policy assessment {ref!r} is not present in canonical assessments."
            )

    missing_units = sorted(
        ref for ref in policy.assessments if policy.assessment_unit(ref) is None
    )
    if missing_units:
        raise SemanticValidationError(
            [
                (
                    "$",
                    "snapshot mode requires a declared unit for every assessment "
                    "used by the policy; canonical/results.json carries no unit, "
                    "so the engine never guesses one. Missing assessmentUnits: "
                    f"{missing_units}.",
                )
            ]
        )

    outcomes: dict[str, object] = {}
    from .engine import calculate

    for subject_id in sorted(subjects_index):
        assessments = {}
        for ref in policy.assessments:
            unit = policy.assessment_unit(ref)
            result = results_index.get((subject_id, ref))
            score_value = _to_score(ref, result.get("score"), unit) if result is not None else None
            present = score_value is not None
            assessments[ref] = AssessmentInput(
                assessment_id=ref,
                present=present,
                value=score_value if present else None,
                status=result.get("status") if present else None,
            )
        inputs = NormalizedInputs(subject_id=subject_id, assessments=assessments)
        outcome = calculate(policy, inputs, context={"sectionId": section_id, "subjectId": subject_id})
        outcomes[subject_id] = outcome

    return {
        POLICY_REL: build_effective_policy(section_id, policy),
        OUTCOMES_REL: outcomes_document(outcomes, section_id),
        TRACES_REL: traces_document(policy, outcomes, section_id),
    }
