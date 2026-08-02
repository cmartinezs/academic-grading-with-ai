"""C2 Grade Policy Engine.

Deterministic, typed, versioned grade calculation authority. Public surface:

- ``load_policy(raw)``  -> validated ``Policy`` (raises on schema/semantic errors)
- ``calculate(policy, inputs, context)`` -> ``EngineOutcome`` (pure/deterministic)
- ``outcomes_document`` / ``traces_document`` -> schema-shaped plain dicts
- ``policy_hash(raw)``  -> deterministic sha256 of the canonical policy doc
- ``version.__version__`` -> engine version
"""

from __future__ import annotations

from .errors import GradePolicyError
from .engine import calculate, outcome_id
from .models import (
    AcademicValue,
    AssessmentInput,
    EngineOutcome,
    NormalizedInputs,
    Policy,
    StageSpec,
)
from .registry import (
    available_conditions,
    available_operators,
    available_rounding_modes,
)
from .trace import (
    outcome_dict,
    outcomes_document,
    policy_hash,
    trace_dict,
    traces_document,
)
from .validator import load_policy
from .version import __version__

__all__ = [
    "AcademicValue",
    "AssessmentInput",
    "EngineOutcome",
    "GradePolicyError",
    "NormalizedInputs",
    "Policy",
    "StageSpec",
    "available_conditions",
    "available_operators",
    "available_rounding_modes",
    "calculate",
    "load_policy",
    "outcome_dict",
    "outcome_id",
    "outcomes_document",
    "policy_hash",
    "trace_dict",
    "traces_document",
    "__version__",
]
