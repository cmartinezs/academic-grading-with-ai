"""additiveBonus: add a constant bonus (or penalty) to a single input."""

from __future__ import annotations

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=additiveBonus expects exactly one input."
        )
    value = ctx.resolve(spec.inputs[0].ref)
    if value is None:
        from ..errors import MissingInputError

        raise MissingInputError(
            f"stages[{spec.id}].operator=additiveBonus: input missing."
        )

    bonus = Decimal(str(spec.params.get("bonus", "0")))

    def _add():
        return value.value + bonus

    result = run(_add)
    return EvalResult(AcademicValue(result, value.unit))


spec = OperatorSpec(
    name="additiveBonus",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {"bonus": {"type": "number"}},
        "additionalProperties": False,
    },
    allowed_phases=("adjustment",),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Adds a constant bonus to the input value.",
)
