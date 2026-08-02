"""sum: addition of all resolved, present inputs."""

from __future__ import annotations

from ..decimal import DZERO, Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec, require_same_unit


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    values = []
    for ref in spec.inputs:
        value = ctx.resolve(ref.ref)
        if value is None:
            if spec.missing_policy == "zero":
                continue
            from ..errors import MissingInputError

            raise MissingInputError(
                f"stages[{spec.id}].operator={spec.operator}: input {ref.ref!r} missing."
            )
        values.append(value)

    require_same_unit(values, spec.operator, spec.id)

    if not values:
        return EvalResult(AcademicValue(DZERO, "scalar"))

    def _sum():
        return sum(v.value for v in values)

    result = run(_sum)
    return EvalResult(AcademicValue(result, values[0].unit))


spec = OperatorSpec(
    name="sum",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={"type": "object", "additionalProperties": False},
    allowed_phases=("normalization", "aggregation"),
    accepted_input_units=("points", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail", "zero"),
    evaluate=_evaluate,
    description="Arithmetic sum of present inputs; missing contributes zero when allowed.",
)
