"""Operator contract for the closed V1 catalog.

Every operator declares:

- name, version, minimum engine version;
- JSON Schema of its ``params`` object;
- allowed phases;
- accepted input units and output unit;
- null/missing behavior;
- allowed missing policies.

The evaluation signature is pure: it receives the evaluation context and the
stage spec and returns an ``EvalResult``. Operators never read files, use the
clock or generate randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from ..errors import MissingInputError
from ..models import AcademicValue, EvalResult, StageSpec, validate_unit


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    version: str
    min_engine_version: str
    params_schema: dict
    allowed_phases: Sequence[str]
    accepted_input_units: Sequence[str]
    output_unit: str
    allowed_missing_policies: Sequence[str]
    evaluate: Callable[[object, StageSpec], EvalResult]
    description: str = ""

    def allows_phase(self, phase: str) -> bool:
        return phase in self.allowed_phases

    def phase_mismatch(self, phase: str) -> bool:
        return phase not in self.allowed_phases

    def accepts_unit(self, unit: str) -> bool:
        return unit in self.accepted_input_units


def require_same_unit(values: Sequence[AcademicValue], operator: str, stage_id: str) -> None:
    if not values:
        return
    first = values[0].unit
    for item in values[1:]:
        if item.unit != first:
            from ..errors import UnitMismatchError

            raise UnitMismatchError(
                f"stages[{stage_id}].operator={operator}: mixed units "
                f"({first} vs {item.unit}) are incompatible."
            )


def require_unit(value: AcademicValue, expected: str, operator: str, stage_id: str) -> None:
    if value.unit != expected:
        from ..errors import UnitMismatchError

        raise UnitMismatchError(
            f"stages[{stage_id}].operator={operator}: unit {value.unit!r} does not "
            f"match expected {expected!r}."
        )


def missing_policy_for(stage: StageSpec) -> str:
    return stage.missing_policy or "fail"


def resolve_present_values(values: Sequence[AcademicValue]) -> Sequence[AcademicValue]:
    return values


def raise_missing(stage: StageSpec, ref: str) -> None:
    raise MissingInputError(
        f"stages[{stage.id}].operator={stage.operator}: required input {ref!r} is "
        "missing and missingPolicy resolves to fail."
    )


def validate_unit_str(unit: str) -> str:
    return validate_unit(unit)
