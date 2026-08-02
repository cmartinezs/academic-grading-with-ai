"""weightedAverage: sum of weight*value over resolved, present inputs."""

from __future__ import annotations

from ..decimal import DZERO, WEIGHT_SUM_TOLERANCE, Decimal, run
from ..models import AcademicValue, EvalResult, StageSpec
from .base import OperatorSpec, require_same_unit, resolve_present_values


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    inputs = spec.inputs
    resolved: list[tuple[AcademicValue, Decimal]] = []
    for ref in inputs:
        value = ctx.resolve(ref.ref)
        if value is None:
            if spec.missing_policy == "zero":
                resolved.append((AcademicValue(DZERO, "percent"), ref.weight or DZERO))
                continue
            from ..errors import MissingInputError

            raise MissingInputError(
                f"stages[{spec.id}].operator={spec.operator}: input {ref.ref!r} missing."
            )
        resolved.append((value, ref.weight or DZERO))

    require_same_unit([v for v, _ in resolved], spec.operator, spec.id)

    weights = [w for _, w in resolved]
    total = sum(weights, DZERO)
    if abs(total - 1) > WEIGHT_SUM_TOLERANCE:
        from ..errors import WeightSumError

        raise WeightSumError(
            f"stages[{spec.id}].operator={spec.operator}: weights sum {total} != 1."
        )

    output_unit = resolved[0][0].unit

    def _sum():
        return sum(v.value * w for v, w in resolved)

    result = run(_sum)
    return EvalResult(AcademicValue(result, output_unit))


spec = OperatorSpec(
    name="weightedAverage",
    version="1.0.0",
    min_engine_version="0.1.0",
    params_schema={
        "type": "object",
        "properties": {"weights": {"type": "object", "additionalProperties": {"type": "number"}}},
        "additionalProperties": False,
    },
    allowed_phases=("aggregation", "conversion"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    output_unit="scalar",
    allowed_missing_policies=("fail", "zero"),
    evaluate=_evaluate,
    description="Weighted arithmetic mean of present inputs; weights must sum to 1.",
)
