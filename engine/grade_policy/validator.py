"""Semantic validator and loader: raw dict -> typed Policy.

Two gates:

1. Schema gate (JSON Schema, Draft 2020-12) against the versioned policy
   schema selected from ``schemaVersion``.
2. Semantic gate (engine-owned): operator/condition catalog membership,
   operator-phase compatibility, typed unit propagation across the DAG,
   phase-order constraints, DAG planning (cycles, unknown refs incl.
   ``condition.params.ref`` and operator-specific refs, dead stages), engine
   version compatibility, result stage reachability and missing-policy
   configuration.

Validation happens before ``calculate`` so a policy that passes
``grade-policy validate`` can never raise ``IndexError``/``KeyError``/
``TypeError``/``ZeroDivisionError`` or a late schema error at runtime: every
error is a typed ``GradePolicyError``.
"""

from __future__ import annotations

import copy
from typing import Mapping, Optional

from jsonschema import Draft202012Validator

from .conditions import CONDITION_PARAM_SCHEMAS, CONDITION_REF_KINDS
from .decimal import DZERO, WEIGHT_SUM_TOLERANCE, to_decimal
from .errors import SchemaValidationError, SemanticValidationError
from .graph import condition_refs, operator_refs, plan
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
    """Stage refs this stage depends on (inputs + condition refs + operator refs)."""
    stage = policy.stages[sid]
    deps = [inp.ref for inp in stage.inputs if inp.ref in policy.stages]
    deps.extend(ref for ref in condition_refs(stage) if ref in policy.stages)
    deps.extend(ref for ref in operator_refs(stage) if ref in policy.stages)
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

    # First pass: operator/condition catalog membership (fail-closed, raised).
    for sid, stage in stage_defs.items():
        require_operator(stage.operator)
        if stage.condition is not None:
            require_condition(stage.condition.get("kind"))

    # Typed unit propagation: checks run only on units the validator can infer
    # statically (declared assessment units). Undeclared units are resolved at
    # runtime and never guessed here. Cycles and unknown refs raise here.
    units = propagate_units(policy)

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

        # ---- arity ----
        arity_error = spec.check_arity(len(stage.inputs))
        if arity_error:
            record(path, arity_error)

        # ---- duplicate input refs ----
        input_refs = [inp.ref for inp in stage.inputs]
        if len(input_refs) != len(set(input_refs)):
            record(path, f"operator={spec.name} has duplicate input refs.")

        # ---- weight rules ----
        if spec.weight_rule == "forbidden":
            for inp in stage.inputs:
                if inp.weight is not None:
                    record(
                        path,
                        f"operator={spec.name} does not accept weights on inputs "
                        f"(weights live only in InputRef for weightedAverage).",
                    )
        elif spec.weight_rule == "required":
            for inp in stage.inputs:
                if inp.weight is None:
                    record(
                        path,
                        f"operator={spec.name} requires a weight on input {inp.ref!r}.",
                    )
                elif inp.weight <= 0:
                    record(
                        path,
                        f"operator={spec.name} input {inp.ref!r} weight must be positive.",
                    )
            total = sum((inp.weight or DZERO) for inp in stage.inputs)
            if abs(total - 1) > WEIGHT_SUM_TOLERANCE:
                record(
                    path,
                    f"operator={spec.name} weights sum {total} != 1 "
                    f"(tolerance {WEIGHT_SUM_TOLERANCE}).",
                )

        # ---- missing policy matrix + minimumOutput config ----
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
                elif units.get(sid) is not None and minimum["unit"] != units.get(sid):
                    record(
                        path,
                        f"missingPolicy minimumOutput unit {minimum['unit']!r} does not "
                        f"match the stage output unit {units.get(sid)!r}; the missing path "
                        "must not change the stage unit.",
                    )

        # ---- condition param schema + reference kind ----
        condition = stage.condition
        if condition is not None:
            kind = condition.get("kind")
            cond_schema = CONDITION_PARAM_SCHEMAS[kind]
            cond_validator = Draft202012Validator(cond_schema)
            cond_errors = sorted(
                cond_validator.iter_errors(condition.get("params", {})),
                key=lambda e: list(e.absolute_path),
            )
            if cond_errors:
                record(f"{path}.condition", cond_errors[0].message)
            else:
                ref = (condition.get("params") or {}).get("ref")
                expected_kind = CONDITION_REF_KINDS.get(kind, "either")
                if ref is not None:
                    if ref not in stage_defs and ref not in policy.assessments:
                        record(
                            f"{path}.condition",
                            f"condition {kind} ref {ref!r} is neither a stage nor an assessment.",
                        )
                    elif expected_kind == "assessment" and ref not in policy.assessments:
                        record(
                            f"{path}.condition",
                            f"condition {kind} ref {ref!r} must be an assessment, not a stage.",
                        )
                    elif expected_kind == "stage" and ref not in stage_defs:
                        record(
                            f"{path}.condition",
                            f"condition {kind} ref {ref!r} must be a stage.",
                        )
                    # static unit-aware checks for conditions that read values
                    if kind == "levelAtLeast":
                        ref_unit = units.get(ref)
                        if ref_unit is not None and ref_unit != "level":
                            record(
                                f"{path}.condition",
                                f"levelAtLeast ref {ref!r} has unit {ref_unit!r}; "
                                "unit 'level' is required (no implicit conversion).",
                            )
                        params = condition.get("params") or {}
                        levels = params.get("levels")
                        level_target = params.get("level")
                        if levels is not None and level_target is not None:
                            if isinstance(level_target, dict):
                                level_target = level_target.get("value")
                            target_str = str(to_decimal(level_target))
                            catalog = [str(to_decimal(lv)) for lv in levels]
                            if target_str not in catalog:
                                record(
                                    f"{path}.condition",
                                    f"levelAtLeast level {level_target!r} is not within "
                                    f"the declared levels {levels!r}.",
                                )
                    elif kind in ("scoreAtLeast", "scoreBelow"):
                        threshold = (condition.get("params") or {}).get("threshold") or {}
                        threshold_unit = threshold.get("unit")
                        ref_unit = units.get(ref)
                        if (
                            threshold_unit is not None
                            and ref_unit is not None
                            and threshold_unit != ref_unit
                        ):
                            record(
                                f"{path}.condition",
                                f"{kind} threshold unit {threshold_unit!r} must match ref "
                                f"{ref!r} unit {ref_unit!r}; no implicit conversion.",
                            )

        # ---- operator params schema ----
        op_validator = Draft202012Validator(spec.params_schema)
        op_errors = sorted(
            op_validator.iter_errors(stage.params),
            key=lambda e: list(e.absolute_path),
        )
        if op_errors:
            record(f"{path}.operator={spec.name}.params", op_errors[0].message)

        # ---- operator referenced refs (existence + expected kind) ----
        for op_ref in spec.references(stage):
            if op_ref.ref not in stage_defs and op_ref.ref not in policy.assessments:
                record(
                    path,
                    f"operator={spec.name} param ref {op_ref.ref!r} is neither a stage "
                    "nor an assessment.",
                )
            elif op_ref.expected_kind == "stage" and op_ref.ref not in stage_defs:
                record(
                    path,
                    f"operator={spec.name} param {op_ref.ref!r} must reference a stage.",
                )
            elif op_ref.expected_kind == "assessment" and op_ref.ref not in policy.assessments:
                record(
                    path,
                    f"operator={spec.name} param {op_ref.ref!r} must reference an assessment.",
                )

        # ---- operator-specific semantic validation ----
        if spec.semantic_validate is not None:
            findings.extend(spec.semantic_validate(stage, policy, units))

        # ---- unit compatibility on inputs (statically known) ----
        known_units = {
            units.get(inp.ref) for inp in stage.inputs if units.get(inp.ref) is not None
        }
        if len(known_units) > 1:
            record(
                path,
                f"operator={spec.name} reads inputs with mixed declared units "
                f"{sorted(known_units)}; a single common unit is required.",
            )
        for inp in stage.inputs:
            produced = units.get(inp.ref)
            if produced is not None and produced not in spec.accepted_input_units:
                record(
                    path,
                    f"operator={spec.name} reads {inp.ref!r} with unit {produced!r} "
                    f"not in accepted units {list(spec.accepted_input_units)!r}.",
                )

    # A stage must never depend (by input, condition or operator ref) on a
    # later phase.
    for sid, stage in stage_defs.items():
        for dep in _stage_dependencies(policy, sid):
            dep_phase = stage_defs[dep].phase
            if PHASE_ORDER[dep_phase] > PHASE_ORDER[stage.phase]:
                record(
                    f"stages[{sid}]",
                    f"stage {sid!r} (phase {stage.phase!r}) depends on stage {dep!r} "
                    f"(phase {dep_phase!r}), a later phase.",
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
