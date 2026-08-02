"""C2 <-> publication snapshot integration.

Turns a validated grade policy plus the canonical snapshot data
(subjects/assessments/results) into the three C2 canonical payloads:

- ``canonical/policy.json``        (mode ``grade-policy-effective``)
- ``canonical/outcomes.json``      (stable result surface)
- ``canonical/traces.json``        (per-stage audit trail)

The integration is deterministic: same canonical data + policy file always
yields the same three documents, so ``contentHash``/``reviewHash`` are stable
across rebuilds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from .decimal import Decimal
from .errors import GradePolicyError, SchemaValidationError, UsageError
from .models import AcademicValue, AssessmentInput, NormalizedInputs
from .trace import outcomes_document, policy_hash, traces_document
from .validator import load_policy
from .version import __version__

OUTCOMES_REL = "canonical/outcomes.json"
TRACES_REL = "canonical/traces.json"
POLICY_REL = "canonical/policy.json"


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


def _assessment_index(canonical: Mapping[str, object]) -> dict[str, dict]:
    assessments = canonical.get("canonical/assessments.json", {})
    payload = assessments if isinstance(assessments, dict) else {}
    items = payload.get("assessments") or []
    return {str(item.get("assessmentId")): item for item in items if item.get("assessmentId")}


def _subjects_index(canonical: Mapping[str, object]) -> dict[str, dict]:
    subjects = canonical.get("canonical/subjects.json", {})
    payload = subjects if isinstance(subjects, dict) else {}
    items = payload.get("subjects") or []
    return {str(item.get("studentId")): item for item in items if item.get("studentId")}


def _results_for(canonical: Mapping[str, object]) -> dict[tuple[str, str], dict]:
    results = canonical.get("canonical/results.json", {})
    payload = results if isinstance(results, dict) else {}
    index: dict[tuple[str, str], dict] = {}
    for item in payload.get("results") or []:
        sid = str(item.get("studentId") or "")
        aid = str(item.get("assessmentId") or "")
        if sid and aid:
            index[(sid, aid)] = item
    return index


def _to_score(value, unit: str = "percent") -> Optional[AcademicValue]:
    if value is None or value == "":
        return None
    try:
        return AcademicValue(Decimal(str(value)), unit)
    except Exception:
        return None


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

    assessment_index = _assessment_index(canonical)
    subjects_index = _subjects_index(canonical)
    results_index = _results_for(canonical)

    for ref in policy.assessments:
        if ref not in assessment_index:
            from .errors import StageReferenceError

            raise StageReferenceError(
                f"policy assessment {ref!r} is not present in canonical assessments."
            )

    outcomes: dict[str, object] = {}
    from .engine import calculate

    for subject_id in sorted(subjects_index):
        assessments = {}
        for ref in policy.assessments:
            result = results_index.get((subject_id, ref))
            unit = policy.assessment_unit(ref) or "percent"
            present = result is not None and _to_score(result.get("score"), unit) is not None
            assessments[ref] = AssessmentInput(
                assessment_id=ref,
                present=present,
                value=_to_score(result.get("score"), unit) if present else None,
                status=(result or {}).get("status") if present else None,
            )
        inputs = NormalizedInputs(subject_id=subject_id, assessments=assessments)
        outcome = calculate(policy, inputs, context={"sectionId": section_id, "subjectId": subject_id})
        outcomes[subject_id] = outcome

    return {
        POLICY_REL: build_effective_policy(section_id, policy),
        OUTCOMES_REL: outcomes_document(outcomes, section_id),
        TRACES_REL: traces_document(policy, outcomes, section_id),
    }
