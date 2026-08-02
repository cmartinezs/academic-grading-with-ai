"""Typed domain models for the C2 grade policy engine.

The engine works on validated, typed objects (never raw dicts). Policy loading
is the single place where raw JSON is converted to models; every conversion
path is covered by the validator before construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .decimal import Decimal, to_decimal

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
        from .decimal import decimal_str

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
class Policy:
    """Validated, typed grade policy (the calculation authority)."""

    policy_id: str
    policy_version: str
    engine_min_version: str
    schema_version: str
    assessments: Sequence[str]
    stages: Mapping[str, StageSpec]
    result_stage_id: str
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    def ordered_stages(self) -> Sequence[str]:
        return tuple(sorted(self.stages.keys()))

    @property
    def stage_ids(self) -> Sequence[str]:
        return self.ordered_stages()

    def stage(self, stage_id: str) -> StageSpec:
        return self.stages[stage_id]


@dataclass(frozen=True)
class EvalResult:
    """Output of one operator evaluation for one stage."""

    value: AcademicValue
    decisions: Sequence[str] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class StageEvaluation:
    """Per-stage record kept by the engine and materialized in the trace."""

    stage: StageSpec
    applied: bool
    input_refs: Sequence[str] = field(default_factory=tuple)
    normalized_inputs: Sequence[dict] = field(default_factory=tuple)
    missing_decisions: Sequence[str] = field(default_factory=tuple)
    condition_decision: Optional[dict] = None
    value_before: Optional[AcademicValue] = None
    value_after: Optional[AcademicValue] = None
    output: Optional[AcademicValue] = None
    decisions: Sequence[str] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)


@dataclass
class EvalContext:
    """Mutable execution context shared across stages of one calculation.

    Holds the validated policy, the subject inputs and the outputs produced so
    far by earlier stages. Operators and conditions read from it; they never
    write files, use the clock or generate randomness.
    """

    policy: Policy
    inputs: NormalizedInputs
    outputs: dict[str, AcademicValue] = field(default_factory=dict)

    def resolve(self, ref: str) -> Optional[AcademicValue]:
        """Resolve a ref to an AcademicValue (assessment input or stage output)."""
        if ref in self.policy.stages:
            return self.outputs.get(ref)
        assessment = self.inputs.get(ref)
        if assessment is not None and assessment.present and assessment.value is not None:
            return assessment.value
        return None

    def present(self, ref: str) -> bool:
        if ref in self.policy.stages:
            return ref in self.outputs
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
    status: str
    finalizable: bool
    stages: Sequence[StageEvaluation]
