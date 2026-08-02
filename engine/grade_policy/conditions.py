"""Closed V1 catalog of conditions.

Conditions gate a stage: the stage is skipped (output remains None, not
"skipped") when the condition is not satisfied. When it is satisfied the stage
runs normally.

Closed set (V1):
- statusEquals
- levelAtLeast
- assessmentPresent
- assessmentMissing
- scoreAtLeast
- scoreBelow

Each condition is a pure predicate: ``(ctx, spec) -> (bool, reason)``.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from .decimal import Decimal
from .models import EvalContext, StageSpec


def _status(ctx: EvalContext, ref: str) -> Optional[str]:
    if ref in ctx.policy.stages:
        return None
    return ctx.inputs.get(ref).status if ctx.inputs.get(ref) else None


def _value(ctx: EvalContext, ref: str):
    return ctx.resolve(ref)


CONDITION_NAMES = (
    "statusEquals",
    "levelAtLeast",
    "assessmentPresent",
    "assessmentMissing",
    "scoreAtLeast",
    "scoreBelow",
)


def evaluate_status_equals(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    status = _status(ctx, params["ref"])
    expected = params["status"]
    return (status == expected), f"statusEquals({params['ref']})={status!r} vs {expected!r}"


def evaluate_level_at_least(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    level = params.get("level", params.get("value"))
    status = _status(ctx, ref)
    if status is None:
        return False, f"levelAtLeast({ref}): no status"
    levels = params.get("levels")
    if levels is None:
        return False, f"levelAtLeast({ref}): no ordered levels provided"
    if status not in levels:
        return False, f"levelAtLeast({ref}): unknown status {status!r}"
    if level not in levels:
        return False, f"levelAtLeast({ref}): unknown target level {level!r}"
    ok = levels.index(status) >= levels.index(level)
    return ok, f"levelAtLeast({ref})={status} >= {level}: {ok}"


def evaluate_present(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    present = ctx.present(ref)
    return present, f"assessmentPresent({ref})={present}"


def evaluate_missing(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    present = ctx.present(ref)
    return (not present), f"assessmentMissing({ref})={not present}"


def evaluate_score_at_least(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    threshold = Decimal(str(params["threshold"]))
    value = ctx.resolve(ref)
    if value is None:
        return False, f"scoreAtLeast({ref}): no value"
    ok = value.value >= threshold
    return ok, f"scoreAtLeast({ref})={value.value} >= {threshold}: {ok}"


def evaluate_score_below(ctx: EvalContext, spec: StageSpec, params: dict) -> tuple[bool, str]:
    ref = params["ref"]
    threshold = Decimal(str(params["threshold"]))
    value = ctx.resolve(ref)
    if value is None:
        return False, f"scoreBelow({ref}): no value"
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
            "level": {"type": "string"},
            "levels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["ref", "level", "levels"],
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
            "threshold": {
                "type": ["number", "string"],
                "pattern": "^-?[0-9]+(\\.[0-9]+)?$",
            },
        },
        "required": ["ref", "threshold"],
        "additionalProperties": False,
    },
    "scoreBelow": {
        "type": "object",
        "properties": {
            "ref": {"type": "string"},
            "threshold": {
                "type": ["number", "string"],
                "pattern": "^-?[0-9]+(\\.[0-9]+)?$",
            },
        },
        "required": ["ref", "threshold"],
        "additionalProperties": False,
    },
}
