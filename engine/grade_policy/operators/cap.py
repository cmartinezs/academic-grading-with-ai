"""cap: clamp the input value to an upper bound (default 100 for percent)."""

from __future__ import annotations

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(f"stages[{spec.id}].operator=cap expects exactly one input.")
    value = ctx.resolve(spec.inputs[0].ref)
    if value is None:
        from ..errors import MissingInputError

        raise MissingInputError(f"stages[{spec.id}].operator=cap: input missing.")
    cap = Decimal(str(spec.params.get("max", "100")))

    def _clamp():
        return min(value.value, cap)

    result = run(_clamp)
    return EvalResult(AcademicValue(result, value.unit))


spec = OperatorSpec(
    name="cap",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {"max": {"type": "number"}},
        "additionalProperties": False,
    },
    allowed_phases=("adjustment", "finalization"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Clamps the input value to an upper bound.",
)
