"""Operator contract for the closed V1 catalog.

Every operator declares:

- name, version, minimum engine version;
- JSON Schema of its ``params`` object;
- allowed phases;
- accepted input units and a ``resolve_output_unit`` function;
- null/missing behavior;
- allowed missing policies.

The evaluation signature is pure: it receives the evaluation context and the
stage spec and returns an ``EvalResult``. Operators never read files, use the
clock or generate randomness.

Missing policy handling is centralized here so every operator records the same
kind of typed ``MissingDecision`` and returns a ``EvalResult`` whose ``state``
is one of the ``StageState`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from ..decimal import DZERO, Decimal
from ..models import (
    AcademicValue,
    EvalResult,
    MissingDecision,
    ResolvedInput,
    StageSpec,
    StageState,
    validate_unit,
)

VALUE = StageState.VALUE


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    version: str
    min_engine_version: str
    params_schema: dict
    allowed_phases: Sequence[str]
    accepted_input_units: Sequence[str]
    resolve_output_unit: Callable[[StageSpec, Mapping[str, Optional[str]]], Optional[str]]
    allowed_missing_policies: Sequence[str]
    evaluate: Callable[[object, StageSpec], EvalResult]
    description: str = ""

    def allows_phase(self, phase: str) -> bool:
        return phase in self.allowed_phases

    def phase_mismatch(self, phase: str) -> bool:
        return phase not in self.allowed_phases

    def accepts_unit(self, unit: str) -> bool:
        return unit in self.accepted_input_units


def common_output_unit(
    stage: StageSpec, input_units: Mapping[str, Optional[str]]
) -> Optional[str]:
    """Output unit for operators that preserve the common input unit.

    Returns ``None`` when the common unit is unknown or the known units differ;
    the validator reports mixed declared units as a semantic finding.
    """
    known = {
        input_units[inp.ref] for inp in stage.inputs if input_units.get(inp.ref) is not None
    }
    if len(known) != 1:
        return None
    return next(iter(known))


def single_input_output_unit(
    stage: StageSpec, input_units: Mapping[str, Optional[str]]
) -> Optional[str]:
    """Output unit for operators that preserve the single input unit."""
    if len(stage.inputs) != 1:
        return None
    return input_units.get(stage.inputs[0].ref)


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


def resolve_inputs(ctx, spec: StageSpec) -> Sequence[ResolvedInput]:
    """Resolve every input ref to its typed state, value and reason."""
    resolved = []
    for ref in spec.inputs:
        value, state, reason = ctx.resolve_ref(ref.ref)
        resolved.append(
            ResolvedInput(
                ref=ref.ref,
                value=value,
                state=state,
                reason=reason,
                weight=ref.weight,
            )
        )
    return resolved


def split_present(resolved: Sequence[ResolvedInput]) -> tuple[list[ResolvedInput], list[ResolvedInput]]:
    present = [r for r in resolved if r.state == VALUE]
    missing = [r for r in resolved if r.state != VALUE]
    return present, missing


def expected_unit(ctx, ref: str) -> Optional[str]:
    """The statically-known unit for a ref, or None when undeclared."""
    if ref in ctx.policy.stages:
        return ctx.units.get(ref)
    return ctx.policy.assessment_unit(ref)


def raise_missing(stage: StageSpec, missing: Sequence[ResolvedInput]) -> None:
    from ..errors import MissingInputError

    first = missing[0]
    detail = f" ({first.state}: {first.reason})" if first.reason else ""
    raise MissingInputError(
        f"stages[{stage.id}].operator={stage.operator}: required input {first.ref!r} "
        f"is missing{detail} and missingPolicy resolves to fail."
    )


def terminal_result(
    spec: StageSpec,
    missing: Sequence[ResolvedInput],
    state: str,
    reason: str,
) -> EvalResult:
    """A non-value EvalResult for ``pending``/``notApplicable`` policies."""
    decisions = [f"missingPolicy: {state} because {reason}"]
    mds = [
        MissingDecision(
            ref=m.ref,
            reason=m.reason or reason,
            policy=spec.missing_policy or "fail",
            original_weight=m.weight,
            effective_weight=None,
            resulting_state=state,
        )
        for m in missing
    ]
    return EvalResult(
        value=None,
        decisions=decisions,
        state=state,
        missing_decisions=mds,
    )


def minimum_result(
    ctx,
    spec: StageSpec,
    missing: Sequence[ResolvedInput],
) -> EvalResult:
    """``minimumOutput`` fallback: emit params.minimum with its explicit unit."""
    minimum = spec.params.get("minimum") or {}
    unit = minimum.get("unit")
    if unit is None:
        unit = next((expected_unit(ctx, m.ref) for m in missing if expected_unit(ctx, m.ref)), None)
    if unit is None:
        from ..errors import UnitMismatchError

        raise UnitMismatchError(
            f"stages[{spec.id}].operator={spec.operator}: minimumOutput requires an "
            "explicit params.minimum.unit when the expected unit is undeclared."
        )
    value = AcademicValue(Decimal(str(minimum.get("value", "0"))), unit)
    mds = [
        MissingDecision(
            ref=m.ref,
            reason=m.reason or "input absent",
            policy="minimumOutput",
            original_weight=m.weight,
            effective_weight=m.weight,
            resulting_state=VALUE,
        )
        for m in missing
    ]
    return EvalResult(
        value=value,
        decisions=["missingPolicy=minimumOutput: output set to params.minimum"],
        state=VALUE,
        missing_decisions=mds,
    )


def fill_zero(
    ctx,
    spec: StageSpec,
    present: Sequence[ResolvedInput],
    missing: Sequence[ResolvedInput],
) -> tuple[list[ResolvedInput], list[MissingDecision]]:
    """Backfill missing inputs with a zero in the stage's expected unit."""
    if present:
        unit = present[0].value.unit if present[0].value is not None else None
    else:
        units = {
            expected_unit(ctx, m.ref)
            for m in missing
            if expected_unit(ctx, m.ref) is not None
        }
        if not units:
            from ..errors import UnitMismatchError

            raise UnitMismatchError(
                f"stages[{spec.id}].operator={spec.operator}: cannot determine the unit "
                "for a zero backfill; declare assessment units in the policy."
            )
        if len(units) > 1:
            from ..errors import UnitMismatchError

            raise UnitMismatchError(
                f"stages[{spec.id}].operator={spec.operator}: mixed declared units "
                f"{sorted(units)} cannot backfill a single zero."
            )
        unit = next(iter(units))
    filled = list(present)
    mds = []
    for m in missing:
        filled.append(
            ResolvedInput(ref=m.ref, value=AcademicValue(DZERO, unit), state=VALUE, weight=m.weight)
        )
        mds.append(
            MissingDecision(
                ref=m.ref,
                reason=m.reason or "input absent",
                policy="zero",
                original_weight=m.weight,
                effective_weight=m.weight,
                resulting_state=VALUE,
            )
        )
    return filled, mds


@dataclass(frozen=True)
class SingleResolution:
    value_input: Optional[ResolvedInput]
    missing_decisions: Sequence[MissingDecision]
    terminal: Optional[EvalResult]


def resolve_single(ctx, spec: StageSpec) -> SingleResolution:
    """Resolve a one-input operator and apply its missing policy.

    Returns the present input plus recorded missing decisions, or a terminal
    ``EvalResult`` (pending/notApplicable/minimumOutput) / raises for ``fail``.
    """
    if len(spec.inputs) != 1:
        from ..errors import SchemaValidationError

        raise SchemaValidationError(
            f"stages[{spec.id}].operator={spec.operator} expects exactly one input."
        )
    resolved = resolve_inputs(ctx, spec)
    inp = resolved[0]
    if inp.state == VALUE:
        return SingleResolution(value_input=inp, missing_decisions=(), terminal=None)

    policy = missing_policy_for(spec)
    if policy == "fail":
        raise_missing(spec, [inp])
    if policy == "pending":
        return SingleResolution(
            value_input=None,
            missing_decisions=(),
            terminal=terminal_result(spec, [inp], "pending", "required input is missing"),
        )
    if policy == "notApplicable":
        return SingleResolution(
            value_input=None,
            missing_decisions=(),
            terminal=terminal_result(spec, [inp], "notApplicable", "required input is missing"),
        )
    if policy == "minimumOutput":
        return SingleResolution(
            value_input=None,
            missing_decisions=(),
            terminal=minimum_result(ctx, spec, [inp]),
        )
    if policy == "zero":
        filled, mds = fill_zero(ctx, spec, [], [inp])
        return SingleResolution(value_input=filled[0], missing_decisions=mds, terminal=None)

    from ..errors import MissingPolicyError

    raise MissingPolicyError(
        f"stages[{spec.id}].operator={spec.operator}: missingPolicy {policy!r} is not "
        f"implemented for single-input operators."
    )


def validate_unit_str(unit: str) -> str:
    return validate_unit(unit)
