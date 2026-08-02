"""Typed errors for the C2 grade policy engine.

Errors carry logical policy paths (e.g. ``stages[presentation-score]``), stageId
and operator names — never absolute paths, PII or academic content.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


class GradePolicyError(Exception):
    """Base error for the grade policy package."""


class SchemaValidationError(GradePolicyError):
    """The policy document failed JSON Schema validation (fail-closed)."""

    def __init__(self, findings: List[Tuple[str, str]]):
        self.findings = findings
        super().__init__(f"Policy schema validation failed ({len(findings)} finding(s))")


class SemanticValidationError(GradePolicyError):
    """The policy passed the schema but violated a semantic invariant."""

    def __init__(self, findings: List[Tuple[str, str]]):
        self.findings = findings
        super().__init__(f"Policy semantic validation failed ({len(findings)} finding(s))")


class UnsupportedOperatorError(GradePolicyError):
    """The operator name is not in the closed V1 catalog."""


class UnsupportedConditionError(GradePolicyError):
    """The condition name is not in the closed V1 catalog."""


class UnsupportedPhaseError(GradePolicyError):
    """The operator is not allowed in the stage phase."""


class MissingPolicyError(GradePolicyError):
    """The missing policy is not allowed for this operator."""


class UnitMismatchError(GradePolicyError):
    """An operator received incompatible units."""


class MissingInputError(GradePolicyError):
    """A required input is absent and the missing policy resolves to fail."""


class WeightSumError(GradePolicyError):
    """The weights of a weightedAverage stage do not sum to 1."""


class NotFinalizableError(GradePolicyError):
    """The calculation ended in a non-finalizable state (e.g. pending)."""


class EngineVersionError(GradePolicyError):
    """The policy requires a newer engine than the installed one."""


class CycleError(GradePolicyError):
    """The stage dependency graph contains a cycle (sanitized report)."""

    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        pretty = " -> ".join(cycle)
        super().__init__(f"Policy stage graph contains a cycle: {pretty}")


class StageReferenceError(GradePolicyError):
    """A stage/assessment reference is broken or self-referential."""


class OutcomeError(GradePolicyError):
    """The result stage is missing, unreachable or not finalizable."""


class UsageError(GradePolicyError):
    """Invalid CLI usage or invalid input file state."""


def error_path(stage_id: Optional[str] = None, operator: Optional[str] = None) -> str:
    parts: List[str] = []
    if stage_id:
        parts.append(f"stages[{stage_id}]")
    if operator:
        parts.append(f"operator={operator}")
    return ".".join(parts) if parts else "$"
