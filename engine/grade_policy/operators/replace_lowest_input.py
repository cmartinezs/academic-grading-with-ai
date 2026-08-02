"""replaceLowestInput: replace the lowest present value with a constant."""

from __future__ import annotations

from typing import Mapping, Optional

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    common_output_unit,
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
        from ..errors import MissingPolicyError

        raise MissingPolicyError(
            f"stages[{spec.id}].operator={spec.operator}: missingPolicy {policy!r} is not "
            "implemented for replaceLowestInput."
        )

    require_same_unit([r.value for r in present], spec.operator, spec.id)

    replacement = Decimal(str(spec.params.get("replacement", "0")))
    min_value = min(v.value.value for v in present)

    def _replace():
        return sum(v.value.value for v in present) - min_value + replacement

    result = run(_replace)
    return EvalResult(
        AcademicValue(result, present[0].value.unit),
        state=VALUE,
    )


spec = OperatorSpec(
    name="replaceLowestInput",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {"replacement": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"}},
        "additionalProperties": False,
    },
    allowed_phases=("aggregation", "adjustment"),
    accepted_input_units=("points", "percent", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "pending", "notApplicable"),
    evaluate=_evaluate,
    description="Replaces the lowest present input with a constant, preserving the sum of the others.",
)
