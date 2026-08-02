"""Semantic validator and loader: raw dict -> typed Policy.

Two gates:

1. Schema gate (JSON Schema, Draft 2020-12) against the versioned policy
   schema selected from ``schemaVersion``.
2. Semantic gate (engine-owned): operator/condition catalog membership,
   operator-phase compatibility, typed unit propagation across the DAG,
   phase-order constraints, DAG planning (cycles, unknown refs incl.
   ``condition.params.ref``, dead stages), engine version compatibility,
   result stage reachability and missing-policy configuration
   (``minimumOutput`` value/unit, ``piecewiseLinearScale`` output unit).
"""

from __future__ import annotations

import copy
from typing import Mapping, Optional

from jsonschema import Draft202012Validator

from .conditions import CONDITION_PARAM_SCHEMAS
from .decimal import to_decimal
from .errors import SchemaValidationError, SemanticValidationError
from .graph import condition_refs, plan
from .models import (
    MISSING_POLICIES,
    PHASES,
    PHASE_ORDER,
    InputRef,
    Policy,
    StageSpec,
    UNITS,
)
from .registry import require_condition, require_operator
from .schemas import select_schema
from .units import propagate_units
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


def _build_policy(raw: dict) -> Policy:
    stages: dict[str, StageSpec] = {}
    for sid, stage in raw["stages"].items():
        inputs = tuple(
            InputRef(
                ref=inp["ref"],
                weight=None if "weight" not in inp else to_decimal(inp["weight"]),
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

    return Policy(
        policy_id=raw["policyId"],
        policy_version=raw["policyVersion"],
        engine_min_version=raw["engineMinVersion"],
        schema_version=raw["schemaVersion"],
        assessments=tuple(raw["assessments"]),
        stages=stages,
        result_stage_id=raw["resultStageId"],
        assessment_units=dict(raw.get("assessmentUnits") or {}),
        raw=copy.deepcopy(raw),
    )


def _stage_dependencies(policy: Policy, sid: str) -> list[str]:
    """Stage refs this stage depends on (inputs + condition refs)."""
    stage = policy.stages[sid]
    deps = [inp.ref for inp in stage.inputs if inp.ref in policy.stages]
    deps.extend(ref for ref in condition_refs(stage) if ref in policy.stages)
    return deps


def _validate_semantics(policy: Policy) -> None:
    findings: list[tuple[str, str]] = []

    def record(path: str, message: str) -> None:
        findings.append((path, message))

    if not is_compatible_engine(policy.engine_min_version):
        from .errors import EngineVersionError
        from .version import __version__

        raise EngineVersionError(
            f"policy requires engineMinVersion {policy.engine_min_version!r} "
            f"but engine is {__version__}."
        )

    stage_defs = policy.stages
    if len(stage_defs) == 0:
        record("$", "policy must declare at least one stage.")

    if policy.result_stage_id not in stage_defs:
        record("$", f"resultStageId {policy.result_stage_id!r} is not a declared stage.")

    for aid, unit in policy.assessment_units.items():
        if aid not in policy.assessments:
            record(
                "$",
                f"assessmentUnits[{aid!r}] is not a declared assessment "
                f"(declared: {sorted(policy.assessments)}).",
            )
        elif unit not in UNITS:
            record("$", f"assessmentUnits[{aid!r}]: unknown unit {unit!r}.")

    for sid, stage in stage_defs.items():
        path = f"stages[{sid}]"
        if sid != stage.id:
            record(path, f"stage key {sid!r} must match stage.id {stage.id!r}.")

        if stage.phase not in PHASES:
            record(path, f"phase {stage.phase!r} unknown.")

        spec = require_operator(stage.operator)
        if spec.phase_mismatch(stage.phase):
            record(
                path,
                f"operator={spec.name} is not allowed in phase {stage.phase!r}.",
            )

        if stage.missing_policy is not None:
            if stage.missing_policy not in MISSING_POLICIES:
                record(path, f"missingPolicy {stage.missing_policy!r} unknown.")
            elif stage.missing_policy not in spec.allowed_missing_policies:
                record(
                    path,
                    f"operator={spec.name} does not allow missingPolicy "
                    f"{stage.missing_policy!r}.",
                )
            if stage.missing_policy == "minimumOutput":
                minimum = stage.params.get("minimum")
                if not isinstance(minimum, dict) or "value" not in minimum or "unit" not in minimum:
                    record(
                        path,
                        "missingPolicy minimumOutput requires params.minimum "
                        "{value, unit} with an explicit value and unit.",
                    )

        if stage.operator == "piecewiseLinearScale":
            output_unit = stage.params.get("outputUnit")
            if output_unit is None:
                record(
                    path,
                    "piecewiseLinearScale requires an explicit params.outputUnit; "
                    "the output unit must not be guessed.",
                )
            elif output_unit not in UNITS:
                record(path, f"piecewiseLinearScale params.outputUnit {output_unit!r} unknown.")

        condition = stage.condition
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
            op_validator.iter_errors(stage.params),
            key=lambda e: list(e.absolute_path),
        )
        if op_errors:
            record(
                f"{path}.operator={spec.name}.params",
                op_errors[0].message,
            )

    # A stage must never depend (by input or condition) on a later phase.
    for sid, stage in stage_defs.items():
        for dep in _stage_dependencies(policy, sid):
            dep_phase = stage_defs[dep].phase
            if PHASE_ORDER[dep_phase] > PHASE_ORDER[stage.phase]:
                record(
                    f"stages[{sid}]",
                    f"stage {sid!r} (phase {stage.phase!r}) depends on stage {dep!r} "
                    f"(phase {dep_phase!r}), a later phase.",
                )

    # Typed unit propagation: checks run only on units the validator can infer
    # statically (declared assessment units). Undeclared units are resolved at
    # runtime and never guessed here.
    units = propagate_units(policy)
    for sid, stage in stage_defs.items():
        spec = require_operator(stage.operator)
        known_units = {
            units.get(inp.ref) for inp in stage.inputs if units.get(inp.ref) is not None
        }
        if len(known_units) > 1:
            record(
                f"stages[{sid}]",
                f"operator={spec.name} reads inputs with mixed declared units "
                f"{sorted(known_units)}; a single common unit is required.",
            )
        for inp in stage.inputs:
            produced = units.get(inp.ref)
            if produced is not None and produced not in spec.accepted_input_units:
                record(
                    f"stages[{sid}]",
                    f"operator={spec.name} reads {inp.ref!r} with unit {produced!r} "
                    f"not in accepted units {list(spec.accepted_input_units)!r}.",
                )

    if findings:
        raise SemanticValidationError(findings)


def load_policy(raw: dict) -> Policy:
    """Validate schema + semantics and return a typed Policy (or raise)."""
    if not isinstance(raw, dict):
        raise SchemaValidationError("policy document must be an object.")
    _validate_schema(raw)
    policy = _build_policy(raw)
    _validate_semantics(policy)

    # Fail fast on graph errors (cycles, unknown refs incl. condition refs,
    # dead stages, phase-ordered dependencies).
    plan(policy)
    return policy
