"""round: explicit rounding of a single input (fixed-point quantization).

Modes: halfUp, halfEven, floor, ceil, truncate.
"""

from __future__ import annotations

from ..decimal import ROUND_MODE_MAP, Decimal
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=round expects exactly one input."
        )
    value = ctx.resolve(spec.inputs[0].ref)
    if value is None:
        from ..errors import MissingInputError

        raise MissingInputError(f"stages[{spec.id}].operator=round: input missing.")

    places = int(spec.params.get("decimalPlaces", 1))
    mode = spec.params.get("mode", "halfEven")
    if mode not in ROUND_MODE_MAP:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(f"stages[{spec.id}].operator=round: unknown mode {mode!r}.")

    quantum = Decimal(1).scaleb(-places)
    from ..decimal import run

    result = run(lambda: value.value.quantize(quantum, rounding=ROUND_MODE_MAP[mode]))
    return EvalResult(AcademicValue(result, value.unit))


spec = OperatorSpec(
    name="round",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {
            "decimalPlaces": {"type": "integer"},
            "mode": {"enum": ["halfUp", "halfEven", "floor", "ceil", "truncate"]},
        },
        "additionalProperties": False,
    },
    allowed_phases=("finalization",),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Rounds the input to a fixed number of decimal places with an explicit mode.",
)
