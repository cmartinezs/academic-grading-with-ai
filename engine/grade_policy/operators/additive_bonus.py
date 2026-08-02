"""additiveBonus: output = target + source, with an optional typed cap.

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``params.target`` must reference an existing stage;
- ``params.source`` must reference an existing assessment or stage;
- target and source must produce compatible units (same, or an explicit
  conversion outside V1 scope);
- ``params.cap`` is optional and must be a typed ``AcademicValue`` whose unit
  matches the target;
- output = ``target + source``; there is no implicit constant bonus and no
  implicit cap.

The reference edges declared here (``target``/``source``) are first-class DAG
dependencies: they participate in unknown-ref validation, cycle detection,
phase ordering, reachability, topological ordering and unit propagation.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import Decimal, decimal_str, run
from ..errors import SchemaValidationError
from ..models import AcademicValue, EvalResult, Policy, StageSpec
from .base import (
    VALUE,
    OperatorReference,
    OperatorSpec,
    apply_missing,
    require_same_unit,
    require_unit,
    resolve_refs,
)


def resolve_output_unit(
    stage: StageSpec, units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return units.get(stage.params.get("target", ""))


def referenced_refs(stage: StageSpec) -> Sequence[OperatorReference]:
    refs = []
    if stage.params.get("target"):
        refs.append(OperatorReference(stage.params["target"], "target", "stage", True))
    if stage.params.get("source"):
        refs.append(OperatorReference(stage.params["source"], "source", "either", True))
    return refs


def semantic_validate(
    stage: StageSpec, policy: Policy, units: Mapping[str, Optional[str]]
) -> Sequence[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    target = stage.params.get("target")
    source = stage.params.get("source")
    if target is not None and target not in policy.stages:
        findings.append(
            (f"stages[{stage.id}]", f"additiveBonus target {target!r} must be a stage.")
        )
    if source is not None and source not in policy.stages and source not in policy.assessments:
        findings.append(
            (f"stages[{stage.id}]", f"additiveBonus source {source!r} is neither a stage nor an assessment.")
        )
    if target and source:
        target_unit = units.get(target)
        source_unit = units.get(source)
        if target_unit is not None and source_unit is not None and target_unit != source_unit:
            findings.append(
                (
                    f"stages[{stage.id}]",
                    f"additiveBonus target {target!r} ({target_unit}) and source {source!r} "
                    f"({source_unit}) have incompatible units; no implicit conversion.",
                )
            )
    cap = stage.params.get("cap")
    if cap is not None:
        if not isinstance(cap, dict) or "value" not in cap or "unit" not in cap:
            findings.append(
                (f"stages[{stage.id}]", "additiveBonus cap must be a typed AcademicValue {value, unit}.")
            )
        else:
            cap_unit = cap.get("unit")
            if cap_unit not in (
                "percent",
                "points",
                "grade",
                "scalar",
                "level",
            ):
                findings.append((f"stages[{stage.id}]", f"additiveBonus cap.unit {cap_unit!r} unknown."))
            elif target and units.get(target) is not None and cap_unit != units.get(target):
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"additiveBonus cap.unit {cap_unit!r} must match the target unit {units.get(target)!r}.",
                    )
                )
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    target = spec.params["target"]
    source = spec.params["source"]

    resolved = resolve_refs(ctx, spec, [target, source])
    present, _mds, terminal = apply_missing(ctx, spec, resolved)
    if terminal is not None:
        return terminal

    target_value = present[0].value
    source_value = present[1].value

    require_same_unit([target_value, source_value], spec.operator, spec.id)

    result = run(lambda: target_value.value + source_value.value)

    cap_applied = False
    cap_value = None
    cap = spec.params.get("cap")
    if cap is not None:
        cap_value = AcademicValue(Decimal(str(cap["value"])), cap["unit"])
        require_unit(cap_value, target_value.unit, spec.operator, spec.id)
        if result > cap_value.value:
            result = cap_value.value
            cap_applied = True

    output = AcademicValue(result, target_value.unit)
    operator_data = {
        "targetBefore": {"value": decimal_str(target_value.value), "unit": target_value.unit},
        "sourceValue": source_value.to_dict(),
        "cap": cap_value.to_dict() if cap_value is not None else None,
        "output": output.to_dict(),
        "capApplied": cap_applied,
    }
    decisions = [f"additiveBonus: {target}={decimal_str(target_value.value)} + {source}={decimal_str(source_value.value)}"]
    if cap_value is not None:
        decisions.append(
            f"additiveBonus cap={decimal_str(cap_value.value)} applied={cap_applied}"
        )
    return EvalResult(
        value=output,
        state=VALUE,
        decisions=decisions,
        operator_data=operator_data,
    )


spec = OperatorSpec(
    name="additiveBonus",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "source": {"type": "string"},
            "cap": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
        },
        "required": ["target", "source"],
        "additionalProperties": False,
    },
    allowed_phases=("adjustment",),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "pending", "notApplicable"),
    evaluate=_evaluate,
    referenced_refs=referenced_refs,
    min_inputs=0,
    max_inputs=0,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Adds a source value to a target stage output, with an optional typed cap.",
)
