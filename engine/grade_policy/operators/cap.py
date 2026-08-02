"""cap: clamp the input value to an explicit typed upper bound.

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``params.cap`` is a required typed ``AcademicValue`` ``{"value", "unit"}`` in
  the same unit as the input; there is no implicit default cap and no ``max``
  param;
- output = ``min(value, cap)``; the decision is visible even when it does not
  modify the value.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import Decimal, decimal_str, run
from ..errors import SchemaValidationError
from ..models import AcademicValue, EvalResult, Policy, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    require_unit,
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
    cap = stage.params.get("cap")
    if not isinstance(cap, dict) or "value" not in cap or "unit" not in cap:
        findings.append((f"stages[{stage.id}]", "cap requires a typed params.cap {value, unit}."))
    else:
        cap_unit = cap.get("unit")
        if cap_unit not in ("percent", "points", "grade", "scalar", "level"):
            findings.append((f"stages[{stage.id}]", f"cap.unit {cap_unit!r} unknown."))
        elif stage.inputs:
            input_unit = units.get(stage.inputs[0].ref)
            if input_unit is not None and cap_unit != input_unit:
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"cap.unit {cap_unit!r} must match the input unit {input_unit!r}.",
                    )
                )
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_single(ctx, spec)
    if resolved.terminal is not None:
        return resolved.terminal
    value = resolved.value_input.value

    cap_raw = spec.params.get("cap")
    if not isinstance(cap_raw, dict) or "value" not in cap_raw or "unit" not in cap_raw:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=cap: params.cap {value, unit} required."
        )
    cap = AcademicValue(Decimal(str(cap_raw["value"])), cap_raw["unit"])
    require_unit(cap, value.unit, spec.operator, spec.id)

    applied = value.value > cap.value

    def _clamp():
        return min(value.value, cap.value)

    result = run(_clamp)
    return EvalResult(
        AcademicValue(result, value.unit),
        state=VALUE,
        decisions=[
            f"cap={decimal_str(cap.value)} applied={applied} "
            f"(input {decimal_str(value.value)})"
        ],
        operator_data={
            "inputBefore": value.to_dict(),
            "cap": cap.to_dict(),
            "output": AcademicValue(result, value.unit).to_dict(),
            "capApplied": applied,
        },
        missing_decisions=resolved.missing_decisions,
    )


spec = OperatorSpec(
    name="cap",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "cap": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
            "minimum": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
        },
        "required": ["cap"],
        "additionalProperties": False,
    },
    allowed_phases=("adjustment", "finalization"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "zero", "minimumOutput", "pending", "notApplicable"),
    evaluate=_evaluate,
    min_inputs=1,
    max_inputs=1,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Clamps the input value to an explicit typed upper bound.",
)
