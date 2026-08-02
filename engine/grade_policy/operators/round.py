"""round: explicit rounding of a single input (fixed-point quantization).

Modes: halfUp, halfEven, floor, ceil, truncate.
"""

from __future__ import annotations

from typing import Mapping, Optional

from ..decimal import ROUND_MODE_MAP, Decimal, run
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

    places = int(spec.params.get("decimalPlaces", 1))
    mode = spec.params.get("mode", "halfEven")
    if mode not in ROUND_MODE_MAP:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(f"stages[{spec.id}].operator=round: unknown mode {mode!r}.")

    quantum = Decimal(1).scaleb(-places)
    result = run(lambda: value.value.quantize(quantum, rounding=ROUND_MODE_MAP[mode]))
    return EvalResult(
        AcademicValue(result, value.unit),
        state=VALUE,
        missing_decisions=resolved.missing_decisions,
    )


spec = OperatorSpec(
    name="round",
    version="1.0.0",
    min_engine_version="0.2.0",
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
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "pending", "notApplicable"),
    evaluate=_evaluate,
    description="Rounds the input to a fixed number of decimal places with an explicit mode.",
)
