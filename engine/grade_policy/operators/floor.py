"""floor: clamp the input value to a lower bound (default 0)."""

from __future__ import annotations

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=floor expects exactly one input."
        )
    value = ctx.resolve(spec.inputs[0].ref)
    if value is None:
        from ..errors import MissingInputError

        raise MissingInputError(f"stages[{spec.id}].operator=floor: input missing.")
    floor = Decimal(str(spec.params.get("min", "0")))

    def _clamp():
        return max(value.value, floor)

    result = run(_clamp)
    return EvalResult(AcademicValue(result, value.unit))


spec = OperatorSpec(
    name="floor",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {"min": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"}},
        "additionalProperties": False,
    },
    allowed_phases=("adjustment", "finalization"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Clamps the input value to a lower bound.",
)
