"""The pure, deterministic grade calculation engine.

Responsibilities:

- execute stages in deterministic topological order;
- evaluate conditions and record the skip decision when not satisfied;
- run each operator with the fixed decimal context;
- build the per-stage trace;
- finalize a single subject outcome.

The engine never reads files, never uses the clock and never randomizes: the
same (policy, inputs, context) tuple always yields the same trace and outcome.
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Optional

from .decimal import DZERO, decimal_str
from .errors import MissingInputError, OutcomeError, UsageError
from .models import (
    AcademicValue,
    EngineOutcome,
    EvalContext,
    EvalResult,
    NormalizedInputs,
    Policy,
    StageEvaluation,
    StageSpec,
)
from .registry import require_operator
from .conditions import CONDITION_EVALUATORS
from .graph import plan


def outcome_id(section_id: Optional[str], subject_id: str, policy: Policy) -> str:
    """Deterministic outcome id: ``out_`` + first 16 hex bytes of a sha256."""
    parts = []
    if section_id:
        parts.append(str(section_id))
    parts.append(str(subject_id))
    parts.append(str(policy.result_stage_id))
    parts.append(str(policy.policy_id))
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"out_{digest}"


def _resolve_inputs(ctx: EvalContext, spec: StageSpec) -> list[tuple[str, Optional[AcademicValue], Optional[object]]]:
    resolved = []
    for ref in spec.inputs:
        value = ctx.resolve(ref.ref)
        resolved.append((ref.ref, value, ref.weight))
    return resolved


def _normalized_input_payload(resolved: list[tuple[str, Optional[AcademicValue], Optional[object]]]) -> list[dict]:
    payload = []
    for ref, value, weight in resolved:
        entry: dict = {"ref": ref, "value": value.to_dict() if value is not None else None}
        if weight is not None:
            entry["weight"] = decimal_str(weight)
        payload.append(entry)
    return payload


def _evaluate_stage(ctx: EvalContext, spec: StageSpec) -> StageEvaluation:
    operator = require_operator(spec.operator)

    condition_decision = None
    if spec.condition is not None:
        evaluator = CONDITION_EVALUATORS[spec.condition["kind"]]
        satisfied, reason = evaluator(ctx, spec, spec.condition["params"])
        condition_decision = {
            "kind": spec.condition["kind"],
            "satisfied": satisfied,
            "reason": reason,
        }
        if not satisfied:
            return StageEvaluation(
                stage=spec,
                applied=False,
                input_refs=tuple(r[0] for r in _resolve_inputs(ctx, spec)),
                normalized_inputs=_normalized_input_payload(_resolve_inputs(ctx, spec)),
                missing_decisions=(),
                condition_decision=condition_decision,
                value_before=None,
                value_after=None,
                output=None,
                decisions=(f"condition {spec.condition['kind']} not satisfied",),
                warnings=(),
            )

    result: EvalResult = operator.evaluate(ctx, spec)
    ctx.outputs[spec.id] = result.value
    return StageEvaluation(
        stage=spec,
        applied=True,
        input_refs=tuple(r[0] for r in _resolve_inputs(ctx, spec)),
        normalized_inputs=_normalized_input_payload(_resolve_inputs(ctx, spec)),
        missing_decisions=(),
        condition_decision=condition_decision,
        value_before=None,
        value_after=result.value,
        output=result.value,
        decisions=tuple(result.decisions),
        warnings=tuple(result.warnings),
    )


def calculate(
    policy: Policy,
    inputs: NormalizedInputs,
    context: Optional[Mapping[str, str]] = None,
) -> EngineOutcome:
    """Run one subject through the policy. Pure and deterministic."""
    context = context or {}
    subject_id = context.get("subjectId") or inputs.subject_id

    ctx = EvalContext(policy=policy, inputs=inputs)
    order = plan(policy).order
    stages: list[StageEvaluation] = []

    for sid in order:
        spec = policy.stages[sid]
        eval = _evaluate_stage(ctx, spec)
        stages.append(eval)

    result_value = ctx.outputs.get(policy.result_stage_id)

    status = "finalized" if result_value is not None else "pending"
    finalizable = result_value is not None

    return EngineOutcome(
        subject_id=subject_id,
        policy=policy,
        result_stage_id=policy.result_stage_id,
        value=result_value,
        status=status,
        finalizable=finalizable,
        stages=tuple(stages),
    )
