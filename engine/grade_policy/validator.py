"""Semantic validator and loader: raw dict -> typed Policy.

Two gates:

1. Schema gate (JSON Schema, Draft 2020-12) against the versioned policy
   schema selected from ``schemaVersion``.
2. Semantic gate (engine-owned): operator/condition catalog membership,
   operator-phase compatibility, unit flow consistency, DAG planning
   (cycles, unknown refs, dead stages), engine version compatibility,
   result stage reachability.
"""

from __future__ import annotations

import copy
from typing import Mapping, Optional

from jsonschema import Draft202012Validator

from .decimal import to_decimal
from .errors import SchemaValidationError, SemanticValidationError
from .graph import plan
from .models import (
    MISSING_POLICIES,
    PHASES,
    InputRef,
    Policy,
    StageSpec,
)
from .registry import require_condition, require_operator
from .conditions import CONDITION_PARAM_SCHEMAS
from .schemas import select_schema
from .version import is_compatible_engine


def _validate_schema(raw: dict) -> None:
    schema = select_schema("policy", raw.get("schemaVersion", ""))
    validator = Draft202012Validator(schema)
    findings = [
        (".".join(map(str, e.absolute_path)) or "$", e.message)
        for e in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    ]
    if findings:
        raise SchemaValidationError(findings)


def _validate_semantics(raw: dict) -> None:
    findings: list[tuple[str, str]] = []

    def record(path: str, message: str) -> None:
        findings.append((path, message))

    if not is_compatible_engine(raw["engineMinVersion"]):
        from .errors import EngineVersionError
        from .version import __version__

        raise EngineVersionError(
            f"policy requires engineMinVersion {raw['engineMinVersion']!r} "
            f"but engine is {__version__}."
        )

    stage_defs: Mapping[str, dict] = raw["stages"]
    if len(stage_defs) == 0:
        record("$", "policy must declare at least one stage.")

    if raw["resultStageId"] not in stage_defs:
        record("$", f"resultStageId {raw['resultStageId']!r} is not a declared stage.")

    assessments = set(raw["assessments"])
    for sid, stage in stage_defs.items():
        path = f"stages[{sid}]"
        if sid != stage.get("id"):
            record(path, f"stage key {sid!r} must match stage.id {stage.get('id')!r}.")

        if stage["phase"] not in PHASES:
            record(path, f"phase {stage['phase']!r} unknown.")

        spec = require_operator(stage["operator"])
        if spec.phase_mismatch(stage["phase"]):
            record(
                path,
                f"operator={spec.name} is not allowed in phase {stage['phase']!r}.",
            )

        if stage.get("missingPolicy") is not None:
            if stage["missingPolicy"] not in MISSING_POLICIES:
                record(path, f"missingPolicy {stage['missingPolicy']!r} unknown.")
            elif stage["missingPolicy"] not in spec.allowed_missing_policies:
                record(
                    path,
                    f"operator={spec.name} does not allow missingPolicy "
                    f"{stage['missingPolicy']!r}.",
                )

        condition = stage.get("condition")
        if condition is not None:
            kind = condition.get("kind")
            require_condition(kind)
            cond_schema = CONDITION_PARAM_SCHEMAS[kind]
            cond_validator = Draft202012Validator(cond_schema)
            cond_errors = sorted(
                cond_validator.iter_errors(condition.get("params", {})),
                key=lambda e: list(e.absolute_path),
            )
            if cond_errors:
                record(
                    f"{path}.condition",
                    cond_errors[0].message,
                )

        op_validator = Draft202012Validator(spec.params_schema)
        op_errors = sorted(
            op_validator.iter_errors(stage.get("params", {})),
            key=lambda e: list(e.absolute_path),
        )
        if op_errors:
            record(
                f"{path}.operator={spec.name}.params",
                op_errors[0].message,
            )

    # Unit flow consistency across stage-to-stage edges (assessments deferred
    # to runtime because their units are only known from the input payloads).
    output_unit: dict[str, str] = {}
    for sid, stage in stage_defs.items():
        output_unit[sid] = require_operator(stage["operator"]).output_unit
    for sid, stage in stage_defs.items():
        spec = require_operator(stage["operator"])
        for inp in stage.get("inputs", []):
            ref = inp["ref"]
            if ref in stage_defs:
                produced = output_unit[ref]
                if produced not in spec.accepted_input_units:
                    record(
                        f"stages[{sid}]",
                        f"operator={spec.name} reads stage {ref!r} with unit "
                        f"{produced!r} not in accepted units {spec.accepted_input_units!r}.",
                    )

    if findings:
        raise SemanticValidationError(findings)


def load_policy(raw: dict) -> Policy:
    """Validate schema + semantics and return a typed Policy (or raise)."""
    if not isinstance(raw, dict):
        raise SchemaValidationError("policy document must be an object.")
    _validate_schema(raw)
    _validate_semantics(raw)

    stages: dict[str, StageSpec] = {}
    for sid, stage in raw["stages"].items():
        inputs = tuple(
            InputRef(
                ref=inp["ref"],
                weight=to_decimal(inp["weight"]) if "weight" in inp else None,
            )
            for inp in stage.get("inputs", [])
        )
        stages[sid] = StageSpec(
            id=stage["id"],
            phase=stage["phase"],
            operator=stage["operator"],
            inputs=inputs,
            params=copy.deepcopy(stage.get("params", {})),
            missing_policy=stage.get("missingPolicy"),
            condition=copy.deepcopy(stage.get("condition")),
        )

    policy = Policy(
        policy_id=raw["policyId"],
        policy_version=raw["policyVersion"],
        engine_min_version=raw["engineMinVersion"],
        schema_version=raw["schemaVersion"],
        assessments=tuple(raw["assessments"]),
        stages=stages,
        result_stage_id=raw["resultStageId"],
        raw=copy.deepcopy(raw),
    )

    # Fail fast on graph errors (cycles, unknown refs, dead stages).
    plan(policy)
    return policy
