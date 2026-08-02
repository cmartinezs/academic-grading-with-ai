"""Closed V1 catalog of conditions.

Conditions gate a stage: the stage is skipped (output remains None, not
"skipped") when the condition is not satisfied. When it is satisfied the stage
runs normally.

Closed set (V1):
- statusEquals       -> compares AssessmentInput.status; ref must be an assessment
- levelAtLeast       -> reads an AcademicValue; requires unit=level; compares value
- assessmentPresent  -> ref must be an assessment
- assessmentMissing  -> ref must be an assessment
- scoreAtLeast       -> unit-aware threshold; ref assessment or stage with value
- scoreBelow         -> unit-aware threshold; ref assessment or stage with value

Each condition is a pure predicate: ``(ctx, spec) -> (bool, reason)``.

Reference-kind rules (validated in the validator):
- statusEquals / assessmentPresent / assessmentMissing: ref must be an
  assessment (for stages, a different condition is introduced in a future
  version; no overloaded semantics here);
- scoreAtLeast / scoreBelow: ref may be an assessment or a stage with a value;
- levelAtLeast: ref may be an assessment (typically) or a stage producing
  ``level``; the unit must be ``level`` (no implicit conversion).
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from .decimal import Decimal, to_decimal
from .errors import UnitMismatchError
from .models import EvalContext, StageSpec

CONDITION_NAMES = (
    "statusEquals",
    "levelAtLeast",
    "assessmentPresent",
    "assessmentMissing",
    "scoreAtLeast",
    "scoreBelow",
)

CONDITION_REF_KINDS: dict[str, str] = {
    "statusEquals": "assessment",
    "levelAtLeast": "either",
    "assessmentPresent": "assessment",
    "assessmentMissing": "assessment",
    "scoreAtLeast": "either",
    "scoreBelow": "either",
}

_DECIMAL_PATTERN = {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"}
_UNIT_ENUM = {"enum": ["percent", "points", "grade", "scalar", "level"]}

_ACADEMIC_VALUE_SCHEMA = {
    "type": "object",
    "required": ["value", "unit"],
    "properties": {"value": _DECIMAL_PATTERN, "unit": _UNIT_ENUM},
    "additionalProperties": False,
}


def _status(ctx: EvalContext, ref: str) -> Optional[str]:
    if ref in ctx.policy.stages:
        return None
    assessment = ctx.inputs.get(ref)
    return assessment.status if assessment is not None else None


def evaluate_status_equals(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    status = _status(ctx, ref)
    expected = params["status"]
    ok = status == expected
    return ok, f"statusEquals({ref})={status!r} vs {expected!r}"


def _level_value(params: dict) -> Decimal:
    target = params["level"]
    if isinstance(target, dict):
        if target.get("unit") != "level":
            raise UnitMismatchError(
                f"levelAtLeast: target unit {target.get('unit')!r} must be 'level'."
            )
        return to_decimal(target["value"])
    return to_decimal(target)


def evaluate_level_at_least(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    value = ctx.resolve(ref)
    if value is None:
        return False, f"levelAtLeast({ref}): no value (fail-closed)"
    if value.unit != "level":
        return False, f"levelAtLeast({ref}): unit {value.unit!r} is not 'level' (no implicit conversion)"
    target_value = _level_value(params)
    ok = value.value >= target_value
    return ok, f"levelAtLeast({ref})={value.value} >= {target_value}: {ok}"


def evaluate_present(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    present = ctx.present(ref)
    return present, f"assessmentPresent({ref})={present}"


def evaluate_missing(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    present = ctx.present(ref)
    return (not present), f"assessmentMissing({ref})={not present}"


def _threshold_value(params: dict) -> tuple[Decimal, str]:
    threshold = params["threshold"]
    if not isinstance(threshold, dict) or "value" not in threshold or "unit" not in threshold:
        raise UnitMismatchError(
            "score conditions require a typed threshold {value, unit}; no implicit conversion."
        )
    return to_decimal(threshold["value"]), threshold["unit"]


def evaluate_score_at_least(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    threshold, unit = _threshold_value(params)
    value = ctx.resolve(ref)
    if value is None:
        return False, f"scoreAtLeast({ref}): no value (fail-closed)"
    if value.unit != unit:
        raise UnitMismatchError(
            f"scoreAtLeast({ref}): threshold unit {unit!r} != value unit {value.unit!r} "
            "(no implicit conversion)."
        )
    ok = value.value >= threshold
    return ok, f"scoreAtLeast({ref})={value.value} >= {threshold}: {ok}"


def evaluate_score_below(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    threshold, unit = _threshold_value(params)
    value = ctx.resolve(ref)
    if value is None:
        return False, f"scoreBelow({ref}): no value (fail-closed)"
    if value.unit != unit:
        raise UnitMismatchError(
            f"scoreBelow({ref}): threshold unit {unit!r} != value unit {value.unit!r} "
            "(no implicit conversion)."
        )
    ok = value.value < threshold
    return ok, f"scoreBelow({ref})={value.value} < {threshold}: {ok}"


CONDITION_EVALUATORS: dict[str, Callable[[EvalContext, StageSpec, dict], tuple[bool, str]]] = {
    "statusEquals": evaluate_status_equals,
    "levelAtLeast": evaluate_level_at_least,
    "assessmentPresent": evaluate_present,
    "assessmentMissing": evaluate_missing,
    "scoreAtLeast": evaluate_score_at_least,
    "scoreBelow": evaluate_score_below,
}


def condition_names() -> Sequence[str]:
    return CONDITION_NAMES


CONDITION_PARAM_SCHEMAS: dict[str, dict] = {
    "statusEquals": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["ref", "status"],
        "additionalProperties": False,
    },
    "levelAtLeast": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "level": {
                "anyOf": [
                    _DECIMAL_PATTERN,
                    {
                        "type": "object",
                        "required": ["value", "unit"],
                        "properties": {"value": _DECIMAL_PATTERN, "unit": _UNIT_ENUM},
                        "additionalProperties": False,
                    },
                ]
            },
            "levels": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[0-9]+(\\.[0-9]+)?$"},
                "minItems": 1,
            },
        },
        "required": ["ref", "level"],
        "additionalProperties": False,
    },
    "assessmentPresent": {
        "type": "object",
        "properties": {"ref": {"type": "string"}},
        "required": ["ref"],
        "additionalProperties": False,
    },
    "assessmentMissing": {
        "type": "object",
        "properties": {"ref": {"type": "string"}},
        "required": ["ref"],
        "additionalProperties": False,
    },
    "scoreAtLeast": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "threshold": _ACADEMIC_VALUE_SCHEMA,
        },
        "required": ["ref", "threshold"],
        "additionalProperties": False,
    },
    "scoreBelow": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "threshold": _ACADEMIC_VALUE_SCHEMA,
        },
        "required": ["ref", "threshold"],
        "additionalProperties": False,
    },
}
