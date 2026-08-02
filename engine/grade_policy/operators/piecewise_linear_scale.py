"""piecewiseLinearScale: map a value across ordered breakpoints.

Each pair is ``{"from": <value>, "to": <value>}``, ascending ``from``. The
first pair starts at negative infinity and the last pair's upper bound is
positive infinity. Values below the first ``from`` clamp to the first ``to``;
values above the last ``from`` clamp to the last ``to``.

The output unit is explicit via ``params.outputUnit``; the input must be
``percent``. This is the only operator that converts between units.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import DZERO, Decimal, run
from ..models import (
    AcademicValue,
    EvalResult,
    MissingDecision,
    ResolvedInput,
    StageSpec,
)
from .base import (
    VALUE,
    OperatorSpec,
    missing_policy_for,
    raise_missing,
    require_unit,
    resolve_inputs,
    terminal_result,
)


def resolve_output_unit(
    stage: StageSpec, input_units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return stage.params.get("outputUnit")


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_inputs(ctx, spec)
    inp: ResolvedInput = resolved[0]
    if inp.state != VALUE:
        policy = missing_policy_for(spec)
        if policy == "fail":
            raise_missing(spec, [inp])
        if policy == "pending":
            return terminal_result(spec, [inp], "pending", "required input is missing")
        if policy == "notApplicable":
            return terminal_result(spec, [inp], "notApplicable", "required input is missing")
        if policy == "zero":
            zero = ResolvedInput(ref=inp.ref, value=AcademicValue(DZERO, "percent"), state=VALUE)
            mds = [
                MissingDecision(
                    ref=inp.ref,
                    reason=inp.reason or "input absent",
                    policy="zero",
                    original_weight=None,
                    effective_weight=None,
                    resulting_state=VALUE,
                )
            ]
            value = zero.value
            _result = _scale(spec, value.value)
            return EvalResult(
                AcademicValue(_result, spec.params.get("outputUnit", "grade")),
                state=VALUE,
                missing_decisions=mds,
            )
        from ..errors import MissingPolicyError

        raise MissingPolicyError(
            f"stages[{spec.id}].operator={spec.operator}: missingPolicy {policy!r} is not "
            "implemented for piecewiseLinearScale."
        )

    value = inp.value
    require_unit(value, "percent", spec.operator, spec.id)

    result = _scale(spec, value.value)
    return EvalResult(AcademicValue(result, spec.params.get("outputUnit", "grade")), state=VALUE)


def _scale(spec: StageSpec, x: Decimal) -> Decimal:
    pairs: Sequence[dict] = spec.params.get("pairs", [])
    if not pairs:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: params.pairs required."
        )
    if pairs[0].get("from") is not None:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: first pair 'from' must be null."
        )

    head_to = Decimal(str(pairs[0]["to"]))
    pivots = [
        (Decimal(str(p["from"])), Decimal(str(p["to"])))
        for p in pairs
        if p["from"] is not None
    ]
    tail_from, tail_to = pivots[-1]

    if x <= pivots[0][0]:
        return head_to
    if x >= tail_from:
        return tail_to
    result = head_to
    for i in range(len(pivots) - 1):
        lo, lo_to = pivots[i]
        hi, hi_to = pivots[i + 1]
        if lo < x <= hi:
            t = (x - lo) / (hi - lo)
            result = lo_to + t * (hi_to - lo_to)
            break
    return run(lambda: result)


spec = OperatorSpec(
    name="piecewiseLinearScale",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "outputUnit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
            "pairs": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {
                            "type": ["number", "null", "string"],
                            "pattern": "^-?[0-9]+(\\.[0-9]+)?$",
                        },
                        "to": {
                            "type": ["number", "string"],
                            "pattern": "^-?[0-9]+(\\.[0-9]+)?$",
                        },
                    },
                    "required": ["from", "to"],
                },
            }
        },
        "required": ["pairs"],
    },
    allowed_phases=("conversion",),
    accepted_input_units=("percent",),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "zero", "pending", "notApplicable"),
    evaluate=_evaluate,
    description="Piecewise linear mapping of a percentage to an explicit output scale.",
)
