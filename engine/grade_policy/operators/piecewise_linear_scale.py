"""piecewiseLinearScale: map a value across ordered breakpoints.

Each pair is ``{"from": <value>, "to": <value>}``, ascending ``from``. The
first pair starts at negative infinity and the last pair's upper bound is
positive infinity. Values below the first ``from`` clamp to the first ``to``;
values above the last ``from`` clamp to the last ``to``.
"""

from __future__ import annotations

from typing import Sequence

from ..decimal import Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec, require_unit


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale expects exactly one input."
        )
    value = ctx.resolve(spec.inputs[0].ref)
    if value is None:
        from ..errors import MissingInputError

        raise MissingInputError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: input missing."
        )
    require_unit(value, "percent", spec.operator, spec.id)

    pairs: Sequence[dict] = spec.params.get("pairs", [])
    if not pairs:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: params.pairs required."
        )
    if pairs[0].get("from") is not None:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: first pair 'from' must be null."
        )

    # First pair maps everything below the next breakpoint to its 'to' value;
    # the last pair maps everything above its 'from' to its 'to' value.
    head_to = Decimal(str(pairs[0]["to"]))
    pivots = [(Decimal(str(p["from"])), Decimal(str(p["to"]))) for p in pairs if p["from"] is not None]
    tail_from, tail_to = pivots[-1]

    x = value.value
    if x <= pivots[0][0]:
        result = head_to
    elif x >= tail_from:
        result = tail_to
    else:
        result = head_to
        for i in range(len(pivots) - 1):
            lo, lo_to = pivots[i]
            hi, hi_to = pivots[i + 1]
            if lo < x <= hi:
                t = (x - lo) / (hi - lo)
                result = lo_to + t * (hi_to - lo_to)
                break

    result = run(lambda: result)
    return EvalResult(AcademicValue(result, "grade"))


spec = OperatorSpec(
    name="piecewiseLinearScale",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {
            "pairs": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {
                            "type": ["number", "null", "string"],
                            "pattern": "^-?[0-9]+(\\.[0-9]+)?$"
                        },
                        "to": {
                            "type": ["number", "string"],
                            "pattern": "^-?[0-9]+(\\.[0-9]+)?$"
                        },
                    },
                    "required": ["from", "to"],
                },
            }
        },
        "required": ["pairs"],
    },
    allowed_phases=("conversion",),
    accepted_input_units=("percent", "scalar"),
    output_unit="grade",
    allowed_missing_policies=("fail",),
    evaluate=_evaluate,
    description="Piecewise linear mapping of a percentage to a grade scale.",
)
