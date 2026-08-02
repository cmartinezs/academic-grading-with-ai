"""round: explicit rounding of a single input (fixed-point quantization).

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``params.decimalPlaces`` (int >= 0) or ``params.quantum`` (decimal string);
- ``params.mode``: halfUp | halfEven | floor | ceil | truncate;
- preserves the unit; the position in the DAG is ``finalization``.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import ROUND_MODE_MAP, Decimal, run
from ..errors import SchemaValidationError
from ..models import AcademicValue, EvalResult, Policy, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    resolve_single,
    single_input_output_unit,
)


def resolve_output_unit(
    stage: StageSpec, units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return single_input_output_unit(stage, units)


def semantic_validate(
    stage: StageSpec, policy: Policy, units: Mapping[str, Optional[str]]
) -> Sequence[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    has_places = stage.params.get("decimalPlaces") is not None
    has_quantum = stage.params.get("quantum") is not None
    if not has_places and not has_quantum:
        findings.append(
            (f"stages[{stage.id}]", "round requires params.decimalPlaces or params.quantum.")
        )
    if has_places and has_quantum:
        findings.append(
            (f"stages[{stage.id}]", "round accepts only one of params.decimalPlaces / params.quantum.")
        )
    places = stage.params.get("decimalPlaces")
    if places is not None and (not isinstance(places, int) or places < 0):
        findings.append((f"stages[{stage.id}]", "round params.decimalPlaces must be an int >= 0."))
    quantum = stage.params.get("quantum")
    if quantum is not None:
        try:
            Decimal(str(quantum))
        except Exception:
            findings.append((f"stages[{stage.id}]", "round params.quantum must be a decimal string."))
    mode = stage.params.get("mode")
    if mode is not None and mode not in ROUND_MODE_MAP:
        findings.append((f"stages[{stage.id}]", f"round params.mode {mode!r} unknown."))
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_single(ctx, spec)
    if resolved.terminal is not None:
        return resolved.terminal
    value = resolved.value_input.value

    mode = spec.params.get("mode", "halfEven")
    if mode not in ROUND_MODE_MAP:
        raise SchemaValidationError(f"stages[{spec.id}].operator=round: unknown mode {mode!r}.")

    places = spec.params.get("decimalPlaces")
    quantum = spec.params.get("quantum")
    if places is None and quantum is None:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=round: params.decimalPlaces or params.quantum required."
        )
    if places is not None and quantum is not None:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=round: only one of decimalPlaces/quantum is allowed."
        )
    if quantum is not None:
        quantum_dec = Decimal(str(quantum))
    else:
        quantum_dec = Decimal(1).scaleb(-int(places))

    result = run(lambda: value.value.quantize(quantum_dec, rounding=ROUND_MODE_MAP[mode]))
    return EvalResult(
        AcademicValue(result, value.unit),
        state=VALUE,
        decisions=[f"round mode={mode} quantum={quantum_dec}"],
        missing_decisions=resolved.missing_decisions,
    )


spec = OperatorSpec(
    name="round",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "decimalPlaces": {"type": "integer", "minimum": 0},
            "quantum": {"type": "string", "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
            "mode": {"enum": ["halfUp", "halfEven", "floor", "ceil", "truncate"]},
        },
        "additionalProperties": False,
    },
    allowed_phases=("finalization",),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "pending", "notApplicable"),
    evaluate=_evaluate,
    min_inputs=1,
    max_inputs=1,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Rounds the input to a fixed number of decimal places (or quantum) with an explicit mode.",
)
