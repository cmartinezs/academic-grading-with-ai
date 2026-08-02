"""Typed domain models for the C2 grade policy engine.

The engine works on validated, typed objects (never raw dicts). Policy loading
is the single place where raw JSON is converted to models; every conversion
path is covered by the validator before construction.

Stage evaluation states (``StageState``) are first-class: a stage never loses
the reason why it did or did not produce a value. ``missing``, ``pending``,
``notApplicable`` and ``skippedCondition`` are distinguishable from each other
and from a real value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence

from .decimal import Decimal, decimal_str, to_decimal

UNITS = ("percent", "points", "grade", "scalar", "level")

PHASES = ("normalization", "aggregation", "adjustment", "conversion", "finalization")

PHASE_ORDER: Mapping[str, int] = {name: index for index, name in enumerate(PHASES)}

MISSING_POLICIES = (
    "fail",
    "excludeAndRenormalize",
    "zero",
    "minimumOutput",
    "pending",
    "notApplicable",
)

ROUNDING_MODES = ("halfUp", "halfEven", "floor", "ceil", "truncate")

TIE_POLICIES = ("replaceFirst", "replaceLast")

OUTSIDE_RANGE_MODES = ("clamp", "reject")


class StageState(str, Enum):
    """Typed result of evaluating one stage (or resolving one input ref).

    ``value`` is the only state that carries an ``AcademicValue``.
    """

    VALUE = "value"
    MISSING = "missing"
    PENDING = "pending"
    NOT_APPLICABLE = "notApplicable"
    SKIPPED_CONDITION = "skippedCondition"


def validate_unit(unit: str) -> str:
    if unit not in UNITS:
        raise ValueError(f"Unknown unit: {unit!r}")
    return unit


@dataclass(frozen=True)
class AcademicValue:
    """A numeric value that always knows its unit."""

    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        validate_unit(self.unit)
        if isinstance(self.value, float):
            object.__setattr__(self, "value", to_decimal(self.value))

    def same_unit(self, other: "AcademicValue") -> bool:
        return self.unit == other.unit

    def with_value(self, value: Decimal) -> "AcademicValue":
        return AcademicValue(value, self.unit)

    @classmethod
    def from_scalar(cls, value, unit: str) -> "AcademicValue":
        return cls(to_decimal(value), unit)

    def to_dict(self) -> dict:
        return {"value": decimal_str(self.value), "unit": self.unit}


@dataclass(frozen=True)
class AssessmentInput:
    """Normalized observed input for one assessment of one subject."""

    assessment_id: str
    present: bool = False
    value: Optional[AcademicValue] = None
    status: Optional[str] = None

    def to_dict(self) -> dict:
        payload: dict = {"assessmentId": self.assessment_id, "present": self.present}
        if self.value is not None:
            payload["value"] = self.value.to_dict()
        if self.status is not None:
            payload["status"] = self.status
        return payload


@dataclass(frozen=True)
class NormalizedInputs:
    """All observed inputs for a single subject (opaque id)."""

    subject_id: str
    assessments: Mapping[str, AssessmentInput] = field(default_factory=dict)

    def get(self, ref: str) -> Optional[AssessmentInput]:
        return self.assessments.get(ref)


@dataclass(frozen=True)
class InputRef:
    ref: str
    weight: Optional[Decimal] = None


@dataclass(frozen=True)
class StageSpec:
    id: str
    phase: str
    operator: str
    inputs: Sequence[InputRef] = field(default_factory=tuple)
    params: dict = field(default_factory=dict)
    missing_policy: Optional[str] = None
    condition: Optional[dict] = None


@dataclass(frozen=True)
class MissingDecision:
    """Why an input did not contribute a real value, and what the policy did."""

    ref: str
    reason: str
    policy: str
    original_weight: Optional[Decimal] = None
    effective_weight: Optional[Decimal] = None
    total_before: Optional[Decimal] = None
    resulting_state: str = "missing"

    def to_dict(self) -> dict:
        def state_str(value) -> str:
            if isinstance(value, StageState):
                return value.value
            return str(value)

        payload: dict = {
            "ref": self.ref,
            "reason": self.reason,
            "policy": self.policy,
        }
        if self.original_weight is not None:
            payload["originalWeight"] = decimal_str(self.original_weight)
        if self.effective_weight is not None:
            payload["effectiveWeight"] = decimal_str(self.effective_weight)
        if self.total_before is not None:
            payload["totalBefore"] = decimal_str(self.total_before)
        payload["resultingState"] = state_str(self.resulting_state)
        return payload


@dataclass(frozen=True)
class ResolvedInput:
    """One input ref resolved to a typed state during an operator run."""

    ref: str
    value: Optional[AcademicValue]
    state: str
    reason: Optional[str] = None
    weight: Optional[Decimal] = None


@dataclass(frozen=True)
class Policy:
    """Validated, typed grade policy (the calculation authority)."""

    policy_id: str
    policy_version: str
    engine_min_version: str
    schema_version: str
    assessments: Sequence[str]
    stages: Mapping[str, StageSpec]
    result_stage_id: str
    assessment_units: Mapping[str, str] = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    def ordered_stages(self) -> Sequence[str]:
        return tuple(sorted(self.stages.keys()))

    @property
    def stage_ids(self) -> Sequence[str]:
        return self.ordered_stages()

    def stage(self, stage_id: str) -> StageSpec:
        return self.stages[stage_id]

    def assessment_unit(self, ref: str) -> Optional[str]:
        return self.assessment_units.get(ref)


@dataclass(frozen=True)
class EvalResult:
    """Output of one operator evaluation for one stage."""

    value: Optional[AcademicValue]
    decisions: Sequence[str] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)
    state: str = StageState.VALUE
    missing_decisions: Sequence[MissingDecision] = field(default_factory=tuple)
    operator_data: Optional[dict] = None


@dataclass(frozen=True)
class StageEvaluation:
    """Per-stage record kept by the engine and materialized in the trace."""

    stage: StageSpec
    state: str
    applied: bool
    input_refs: Sequence[str] = field(default_factory=tuple)
    normalized_inputs: Sequence[dict] = field(default_factory=tuple)
    missing_decisions: Sequence[MissingDecision] = field(default_factory=tuple)
    condition_decision: Optional[dict] = None
    value_before: Optional[AcademicValue] = None
    value_after: Optional[AcademicValue] = None
    output: Optional[AcademicValue] = None
    decisions: Sequence[str] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)
    operator_data: Optional[dict] = None


@dataclass
class EvalContext:
    """Mutable execution context shared across stages of one calculation.

    Holds the validated policy, the subject inputs, the outputs produced so far
    by earlier stages and the typed state of every evaluated stage. Operators
    and conditions read from it; they never write files, use the clock or
    generate randomness.
    """

    policy: Policy
    inputs: NormalizedInputs
    outputs: dict[str, AcademicValue] = field(default_factory=dict)
    stage_states: dict[str, str] = field(default_factory=dict)
    stage_reasons: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from .units import propagate_units

        self.units: Mapping[str, Optional[str]] = propagate_units(self.policy)

    def resolve_ref(self, ref: str) -> tuple[Optional[AcademicValue], str, Optional[str]]:
        """Resolve a ref to ``(value, state, reason)``.

        Only ``value`` state carries a value. The reason explains why a
        non-value state happened (including why an upstream stage did not
        produce an output), so downstream missing decisions can propagate it.
        """
        if ref in self.policy.stages:
            state = self.stage_states.get(ref, StageState.MISSING)
            if state == StageState.VALUE:
                return self.outputs.get(ref), state, None
            reason = self.stage_reasons.get(ref) or f"stage {ref!r} is {state}"
            return None, state, reason
        assessment = self.inputs.get(ref)
        if assessment is not None and assessment.present and assessment.value is not None:
            declared = self.policy.assessment_unit(ref)
            if declared is not None and assessment.value.unit != declared:
                from .errors import UnitMismatchError

                raise UnitMismatchError(
                    f"assessment {ref!r}: observed unit {assessment.value.unit!r} does not "
                    f"match declared unit {declared!r} in the policy."
                )
            return assessment.value, StageState.VALUE, None
        if assessment is not None and assessment.status:
            reason = f"status={assessment.status}"
        elif assessment is not None:
            reason = "not present"
        else:
            reason = "unknown assessment"
        return None, StageState.MISSING, reason

    def resolve(self, ref: str) -> Optional[AcademicValue]:
        """Resolve a ref to an AcademicValue, or None when it has no value."""
        value, state, _ = self.resolve_ref(ref)
        return value

    def present(self, ref: str) -> bool:
        if ref in self.policy.stages:
            return self.stage_states.get(ref, StageState.MISSING) == StageState.VALUE
        assessment = self.inputs.get(ref)
        return assessment is not None and assessment.present

    def status_of(self, ref: str) -> Optional[str]:
        if ref in self.policy.stages:
            return None
        assessment = self.inputs.get(ref)
        return assessment.status if assessment is not None else None


@dataclass(frozen=True)
class EngineOutcome:
    """Result of the pure engine for one subject."""

    subject_id: str
    policy: Policy
    result_stage_id: str
    value: Optional[AcademicValue]
    state: str
    status: str
    finalizable: bool
    stages: Sequence[StageEvaluation]
