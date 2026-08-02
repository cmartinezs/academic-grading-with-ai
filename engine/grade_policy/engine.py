"""The pure, deterministic grade calculation engine.

Responsibilities:

- execute stages in deterministic topological order;
- evaluate conditions and record the typed skip decision when not satisfied;
- run each operator with the fixed decimal context;
- track the typed ``StageState`` of every stage (value/missing/pending/
  notApplicable/skippedCondition) so downstream stages can explain why a
  dependency did not produce a value;
- build the per-stage trace;
- finalize a single subject outcome.

The engine never reads files, never uses the clock and never randomizes: the
same (policy, inputs, context) tuple always yields the same trace and outcome.
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Optional

from .decimal import decimal_str
from .errors import OutcomeError, UsageError
from .models import (
    AcademicValue,
    EngineOutcome,
    EvalContext,
    EvalResult,
    NormalizedInputs,
    Policy,
    StageEvaluation,
    StageSpec,
    StageState,
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


def _resolve_inputs(ctx: EvalContext, spec: StageSpec) -> list[tuple[str, Optional[AcademicValue], Optional[object], str, Optional[str]]]:
    resolved = []
    for ref in spec.inputs:
        value, state, reason = ctx.resolve_ref(ref.ref)
        resolved.append((ref.ref, value, ref.weight, state, reason))
    return resolved


def _normalized_input_payload(
    resolved: list[tuple[str, Optional[AcademicValue], Optional[object], str, Optional[str]]],
) -> list[dict]:
    payload = []
    for ref, value, weight, state, reason in resolved:
        entry: dict = {
            "ref": ref,
            "value": value.to_dict() if value is not None else None,
            "state": state,
        }
        if reason is not None:
            entry["reason"] = reason
        if weight is not None:
            entry["weight"] = decimal_str(weight)
        payload.append(entry)
    return payload


def _evaluate_stage(ctx: EvalContext, spec: StageSpec) -> StageEvaluation:
    operator = require_operator(spec.operator)
    resolved = _resolve_inputs(ctx, spec)

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
            ctx.stage_states[spec.id] = StageState.SKIPPED_CONDITION
            ctx.stage_reasons[spec.id] = (
                f"condition {spec.condition['kind']} not satisfied: {reason}"
            )
            return StageEvaluation(
                stage=spec,
                state=StageState.SKIPPED_CONDITION,
                applied=False,
                input_refs=tuple(r[0] for r in resolved),
                normalized_inputs=_normalized_input_payload(resolved),
                missing_decisions=(),
                condition_decision=condition_decision,
                value_before=None,
                value_after=None,
                output=None,
                decisions=(f"condition {spec.condition['kind']} not satisfied",),
                warnings=(),
            )

    result: EvalResult = operator.evaluate(ctx, spec)

    if result.state == StageState.VALUE and result.value is not None:
        ctx.outputs[spec.id] = result.value
        ctx.stage_states[spec.id] = StageState.VALUE
        ctx.stage_reasons.pop(spec.id, None)
    else:
        ctx.stage_states[spec.id] = result.state
        ctx.stage_reasons[spec.id] = "; ".join(result.decisions) or f"stage {spec.id} {result.state}"

    return StageEvaluation(
        stage=spec,
        state=result.state,
        applied=True,
        input_refs=tuple(r[0] for r in resolved),
        normalized_inputs=_normalized_input_payload(resolved),
        missing_decisions=tuple(result.missing_decisions),
        condition_decision=condition_decision,
        value_before=None,
        value_after=result.value,
        output=result.value,
        decisions=tuple(result.decisions),
        warnings=tuple(result.warnings),
    )


def _outcome_state(result_state: str) -> tuple[str, bool, Optional[AcademicValue]]:
    if result_state == StageState.VALUE:
        return "finalized", True, None
    if result_state == StageState.PENDING:
        return "pending", False, None
    if result_state == StageState.NOT_APPLICABLE:
        return "notApplicable", False, None
    # skippedCondition / missing -> non-finalizable pending
    return "pending", False, None


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
        stages.append(_evaluate_stage(ctx, spec))

    result_stage_id = policy.result_stage_id
    result_value = ctx.outputs.get(result_stage_id)
    result_state = ctx.stage_states.get(
        result_stage_id,
        StageState.MISSING if result_value is None else StageState.VALUE,
    )

    status, finalizable, value = _outcome_state(result_state)
    if result_state == StageState.VALUE:
        value = result_value

    return EngineOutcome(
        subject_id=subject_id,
        policy=policy,
        result_stage_id=result_stage_id,
        value=value,
        state=result_state,
        status=status,
        finalizable=finalizable,
        stages=tuple(stages),
    )
