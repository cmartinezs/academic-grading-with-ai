"""Structured trace and outcome serialization.

These functions convert engine results into the plain, schema-shaped dicts
that are later canonically serialized by ``jsonutil`` and written to
``canonical/outcomes.json`` and ``canonical/traces.json``.

Documents are emitted with ``schemaVersion``/``traceSchemaVersion`` ``1.1.0``:
the 1.0.0 shape is preserved and extended additively with typed stage states
and structured missing decisions (compatible minor version).
"""

from __future__ import annotations

from typing import Mapping, Optional

from .decimal import decimal_str
from .models import AcademicValue, EngineOutcome
from .version import __version__

OUTCOMES_SCHEMA_VERSION = "1.1.0"
TRACES_SCHEMA_VERSION = "1.1.0"


def value_dict(value: Optional[AcademicValue]) -> Optional[dict]:
    if value is None:
        return None
    return {"value": decimal_str(value.value), "unit": value.unit}


def outcome_dict(outcome: EngineOutcome, section_id: Optional[str] = None) -> dict:
    from .engine import outcome_id

    payload: dict = {
        "subjectId": outcome.subject_id,
        "outcomeId": outcome_id(section_id, outcome.subject_id, outcome.policy),
        "policyId": outcome.policy.policy_id,
        "status": outcome.status,
        "resultState": outcome.state,
        "finalizable": outcome.finalizable,
        "resultStageId": outcome.result_stage_id,
    }
    if outcome.value is not None:
        payload["value"] = value_dict(outcome.value)
    return payload


def trace_dict(outcome: EngineOutcome, section_id: Optional[str] = None) -> dict:
    from .engine import outcome_id

    stages = []
    for ev in outcome.stages:
        stage_payload: dict = {
            "stageId": ev.stage.id,
            "phase": ev.stage.phase,
            "operator": ev.stage.operator,
            "state": ev.state,
            "applied": ev.applied,
        }
        stage_payload["inputs"] = list(ev.normalized_inputs)
        if ev.output is not None:
            stage_payload["output"] = value_dict(ev.output)
        if ev.missing_decisions:
            stage_payload["missingDecisions"] = [md.to_dict() for md in ev.missing_decisions]
        if ev.condition_decision is not None:
            stage_payload["condition"] = ev.condition_decision
        if ev.operator_data is not None:
            stage_payload["operatorData"] = ev.operator_data
        if ev.decisions:
            stage_payload["decisions"] = list(ev.decisions)
        if ev.warnings:
            stage_payload["warnings"] = list(ev.warnings)
        stages.append(stage_payload)

    return {
        "subjectId": outcome.subject_id,
        "outcomeId": outcome_id(section_id, outcome.subject_id, outcome.policy),
        "policyId": outcome.policy.policy_id,
        "resultState": outcome.state,
        "stages": stages,
    }


def traces_document(
    policy: object,
    outcomes: Mapping[str, EngineOutcome],
    section_id: Optional[str] = None,
) -> dict:
    return {
        "traceSchemaVersion": TRACES_SCHEMA_VERSION,
        "policy": getattr(policy, "raw", policy),
        "subjectTraces": [trace_dict(o, section_id) for o in outcomes.values()],
    }


def outcomes_document(
    outcomes: Mapping[str, EngineOutcome], section_id: Optional[str] = None
) -> dict:
    return {
        "schemaVersion": OUTCOMES_SCHEMA_VERSION,
        "subjectOutcomes": [outcome_dict(o, section_id) for o in outcomes.values()],
    }


def policy_hash(raw_policy: dict) -> str:
    """Deterministic sha256 of the canonical policy document."""
    from .serialize import sha256_text, serialize

    return sha256_text(serialize(raw_policy))


def hashlib_hex(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()
