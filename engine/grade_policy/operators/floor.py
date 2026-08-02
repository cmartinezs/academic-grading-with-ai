"""floor: clamp the input value to a lower bound (default 0)."""

from __future__ import annotations

from typing import Mapping, Optional

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    resolve_single,
    single_input_output_unit,
)


def resolve_output_unit(
    stage: StageSpec, input_units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return single_input_output_unit(stage, input_units)


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_single(ctx, spec)
    if resolved.terminal is not None:
        return resolved.terminal
    value = resolved.value_input.value
    floor = Decimal(str(spec.params.get("min", "0")))

    def _clamp():
        return max(value.value, floor)

    result = run(_clamp)
    return EvalResult(
        AcademicValue(result, value.unit),
        state=VALUE,
        missing_decisions=resolved.missing_decisions,
    )


spec = OperatorSpec(
    name="floor",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "min": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
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
    allowed_phases=("adjustment", "finalization"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "zero", "minimumOutput", "pending", "notApplicable"),
    evaluate=_evaluate,
    description="Clamps the input value to a lower bound.",
)
