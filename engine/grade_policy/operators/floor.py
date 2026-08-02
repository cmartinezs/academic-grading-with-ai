"""floor: clamp the input value to an explicit typed lower bound.

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``params.floor`` is a required typed ``AcademicValue`` ``{"value", "unit"}`` in
  the same unit as the input; there is no implicit default floor and no ``min``
  param;
- output = ``max(value, floor)``; the decision is visible.
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
    floor = stage.params.get("floor")
    if not isinstance(floor, dict) or "value" not in floor or "unit" not in floor:
        findings.append((f"stages[{stage.id}]", "floor requires a typed params.floor {value, unit}."))
    else:
        floor_unit = floor.get("unit")
        if floor_unit not in ("percent", "points", "grade", "scalar", "level"):
            findings.append((f"stages[{stage.id}]", f"floor.unit {floor_unit!r} unknown."))
        elif stage.inputs:
            input_unit = units.get(stage.inputs[0].ref)
            if input_unit is not None and floor_unit != input_unit:
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"floor.unit {floor_unit!r} must match the input unit {input_unit!r}.",
                    )
                )
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_single(ctx, spec)
    if resolved.terminal is not None:
        return resolved.terminal
    value = resolved.value_input.value

    floor_raw = spec.params.get("floor")
    if not isinstance(floor_raw, dict) or "value" not in floor_raw or "unit" not in floor_raw:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=floor: params.floor {value, unit} required."
        )
    floor = AcademicValue(Decimal(str(floor_raw["value"])), floor_raw["unit"])
    require_unit(floor, value.unit, spec.operator, spec.id)

    applied = value.value < floor.value

    def _clamp():
        return max(value.value, floor.value)

    result = run(_clamp)
    return EvalResult(
        AcademicValue(result, value.unit),
        state=VALUE,
        decisions=[
            f"floor={decimal_str(floor.value)} applied={applied} "
            f"(input {decimal_str(value.value)})"
        ],
        operator_data={
            "inputBefore": value.to_dict(),
            "floor": floor.to_dict(),
            "output": AcademicValue(result, value.unit).to_dict(),
            "floorApplied": applied,
        },
        missing_decisions=resolved.missing_decisions,
    )


spec = OperatorSpec(
    name="floor",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "floor": {
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
        "required": ["floor"],
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
    description="Clamps the input value to an explicit typed lower bound.",
)
