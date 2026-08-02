"""sum: addition of all resolved inputs (weights forbidden).

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``inputs``: refs; weights are rejected (only ``InputRef`` carries weights and
  only ``weightedAverage`` accepts them);
- all present inputs must share the same unit;
- optional typed params: ``cap`` and ``floor``, both ``AcademicValue`` in the
  same unit as the input (applied as ``min(max(sum, floor), cap)``);
- ``excludeAndRenormalize`` is incompatible (rejected).
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import DZERO, Decimal, decimal_str, run
from ..errors import SchemaValidationError
from ..models import AcademicValue, EvalResult, Policy, ResolvedInput, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    common_output_unit,
    fill_zero,
    minimum_result,
    missing_policy_for,
    raise_missing,
    require_same_unit,
    require_unit,
    resolve_inputs,
    split_present,
    terminal_result,
)


def resolve_output_unit(
    stage: StageSpec, units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return common_output_unit(stage, units)


def _typed_bound(stage: StageSpec, name: str):
    bound = stage.params.get(name)
    if bound is None:
        return None
    if not isinstance(bound, dict) or "value" not in bound or "unit" not in bound:
        raise SchemaValidationError(
            f"stages[{stage.id}].operator=sum: params.{name} must be a typed AcademicValue {{value, unit}}."
        )
    return AcademicValue(Decimal(str(bound["value"])), bound["unit"])


def semantic_validate(
    stage: StageSpec, policy: Policy, units: Mapping[str, Optional[str]]
) -> Sequence[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for name in ("cap", "floor"):
        bound = stage.params.get(name)
        if bound is None:
            continue
        if not isinstance(bound, dict) or "value" not in bound or "unit" not in bound:
            findings.append((f"stages[{stage.id}]", f"sum params.{name} must be a typed AcademicValue."))
            continue
        unit = bound.get("unit")
        if unit not in ("percent", "points", "grade", "scalar", "level"):
            findings.append((f"stages[{stage.id}]", f"sum params.{name}.unit {unit!r} unknown."))
            continue
        if stage.inputs:
            input_unit = units.get(stage.inputs[0].ref)
            if input_unit is not None and unit != input_unit:
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"sum params.{name}.unit {unit!r} must match the input unit {input_unit!r}.",
                    )
                )
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_inputs(ctx, spec)
    present, missing = split_present(resolved)
    policy = missing_policy_for(spec)

    if missing:
        if policy == "fail":
            raise_missing(spec, missing)
        if policy == "pending":
            return terminal_result(spec, missing, "pending", "required input is missing")
        if policy == "notApplicable":
            return terminal_result(spec, missing, "notApplicable", "required input is missing")
        if policy == "minimumOutput":
            return minimum_result(ctx, spec, missing)
        if policy == "zero":
            present, zero_mds = fill_zero(ctx, spec, present, missing)
    else:
        zero_mds = []

    require_same_unit([r.value for r in present], spec.operator, spec.id)

    if not present:
        unit = next(
            (ctx.policy.assessment_unit(m.ref) for m in resolved if ctx.policy.assessment_unit(m.ref)),
            None,
        )
        if unit is None:
            unit = next((ctx.units.get(m.ref) for m in resolved if m.ref in ctx.policy.stages), None)
        if unit is None:
            from ..errors import UnitMismatchError

            raise UnitMismatchError(
                f"stages[{spec.id}].operator={spec.operator}: no present inputs and no "
                "declared unit for the zero result; declare assessment units in the policy."
            )
        return EvalResult(
            AcademicValue(DZERO, unit),
            state=VALUE,
            missing_decisions=zero_mds,
        )

    def _sum():
        return sum(v.value.value for v in present)

    result = run(_sum)
    output_unit = present[0].value.unit

    cap = _typed_bound(spec, "cap")
    floor = _typed_bound(spec, "floor")
    if cap is not None:
        require_unit(cap, output_unit, spec.operator, spec.id)
        result = run(lambda: min(result, cap.value))
    if floor is not None:
        require_unit(floor, output_unit, spec.operator, spec.id)
        result = run(lambda: max(result, floor.value))

    return EvalResult(
        AcademicValue(result, output_unit),
        state=VALUE,
        decisions=[
            f"sum={decimal_str(result)}"
            + (f" cap={decimal_str(cap.value)}" if cap is not None else "")
            + (f" floor={decimal_str(floor.value)}" if floor is not None else "")
        ],
        operator_data={
            "sum": decimal_str(result),
            "cap": cap.to_dict() if cap is not None else None,
            "floor": floor.to_dict() if floor is not None else None,
            "output": AcademicValue(result, output_unit).to_dict(),
        },
        missing_decisions=zero_mds,
    )


spec = OperatorSpec(
    name="sum",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "cap": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
            "floor": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
            "minimum": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    },
    allowed_phases=("normalization", "aggregation"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=(
        "fail",
        "zero",
        "minimumOutput",
        "pending",
        "notApplicable",
    ),
    evaluate=_evaluate,
    min_inputs=1,
    max_inputs=None,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Arithmetic sum of present inputs with optional typed cap/floor; missing contributes zero when allowed.",
)
