"""replaceLowestInput: replace the lowest present value with a constant."""

from __future__ import annotations

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec, require_same_unit


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) < 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=replaceLowestInput expects at least one input."
        )
    values = []
    for ref in spec.inputs:
        value = ctx.resolve(ref.ref)
        if value is None:
            from ..errors import MissingInputError

            raise MissingInputError(
                f"stages[{spec.id}].operator=replaceLowestInput: input {ref.ref!r} missing."
            )
        values.append(value)

    require_same_unit(values, spec.operator, spec.id)

    replacement = Decimal(str(spec.params.get("replacement", "0")))
    min_value = min(v.value for v in values)

    def _replace():
        return sum(v.value for v in values) - min_value + replacement

    result = run(_replace)
    return EvalResult(AcademicValue(result, values[0].unit))


spec = OperatorSpec(
    name="replaceLowestInput",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {"replacement": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"}},
        "additionalProperties": False,
    },
    allowed_phases=("aggregation", "adjustment"),
    accepted_input_units=("points", "percent", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Replaces the lowest present input with a constant, preserving the sum of the others.",
)
