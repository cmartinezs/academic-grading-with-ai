"""sum: addition of all resolved inputs (weights ignored)."""

from __future__ import annotations

from typing import Mapping, Optional

from ..decimal import DZERO, Decimal, run
from ..models import AcademicValue, EvalResult, ResolvedInput, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    common_output_unit,
    fill_zero,
    minimum_result,
    missing_policy_for,
    raise_missing,
    require_same_unit,
    resolve_inputs,
    split_present,
    terminal_result,
)


def resolve_output_unit(
    stage: StageSpec, input_units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return common_output_unit(stage, input_units)


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
    return EvalResult(
        AcademicValue(result, present[0].value.unit),
        state=VALUE,
        missing_decisions=zero_mds,
    )


spec = OperatorSpec(
    name="sum",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
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
    description="Arithmetic sum of present inputs; missing contributes zero when allowed.",
)
