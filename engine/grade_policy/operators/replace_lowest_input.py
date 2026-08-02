"""replaceLowestInput: replace the lowest present input of a target
``weightedAverage`` stage with a source value, then recompute the average.

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``params.target`` must reference a stage whose operator is ``weightedAverage``;
- ``params.source`` must reference an existing assessment or stage;
- ``params.tiePolicy`` ∈ {``replaceFirst``, ``replaceLast``};
- the gate condition (e.g. ``levelAtLeast``) lives in ``stage.condition`` — the
  only place conditions are kept; when the condition is not satisfied the stage
  is ``skippedCondition``;
- exactly one candidate is replaced; the average is recomputed with the same
  effective weights; the output is a weighted average, never a sum;
- no constant replacement is accepted.

V1 target restriction (explicit limitation; see contract §6): the target must
declare ``missingPolicy`` ``fail`` (or none) and must not declare a ``condition``.
At runtime the target state is resolved before candidates are read and must be
``value``; every candidate is present, so the original weights equal the
effective weights (no exclusion or renormalization).

The ``target``/``source`` reference edges are first-class DAG dependencies.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import DZERO, Decimal, decimal_str, run
from ..models import AcademicValue, EvalResult, Policy, StageSpec
from .base import (
    VALUE,
    OperatorReference,
    OperatorSpec,
    apply_missing,
    require_same_unit,
    resolve_refs,
)
from ..errors import MissingInputError, SchemaValidationError


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
    if target is not None and target not in policy.stages:
        findings.append(
            (f"stages[{stage.id}]", f"replaceLowestInput target {target!r} must be a stage.")
        )
    elif target in policy.stages:
        target_stage = policy.stages[target]
        if target_stage.operator != "weightedAverage":
            findings.append(
                (
                    f"stages[{stage.id}]",
                    f"replaceLowestInput target {target!r} must be a weightedAverage "
                    f"stage; got operator {target_stage.operator!r}.",
                )
            )
        else:
            target_policy = target_stage.missing_policy
            if target_policy not in (None, "fail"):
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"replaceLowestInput target {target!r} must declare "
                        f"missingPolicy fail (or none) in V1; got "
                        f"{target_policy!r}. Every candidate must be present so the "
                        "original weights equal the effective weights.",
                    )
                )
            if target_stage.condition is not None:
                findings.append(
                    (
                        f"stages[{stage.id}]",
                        f"replaceLowestInput target {target!r} must not declare a "
                        "condition in V1; the target must be an unconditional "
                        "weightedAverage stage in state=value.",
                    )
                )
    source = stage.params.get("source")
    if source is not None and source not in policy.stages and source not in policy.assessments:
        findings.append(
            (f"stages[{stage.id}]", f"replaceLowestInput source {source!r} is neither a stage nor an assessment.")
        )
    tie_policy = stage.params.get("tiePolicy")
    if tie_policy is not None and tie_policy not in ("replaceFirst", "replaceLast"):
        findings.append(
            (f"stages[{stage.id}]", f"replaceLowestInput tiePolicy {tie_policy!r} must be replaceFirst or replaceLast.")
        )
    if target in policy.stages:
        target_stage = policy.stages[target]
        if target_stage.operator == "weightedAverage":
            source_unit = units.get(source) if source else None
            for inp in target_stage.inputs:
                cand_unit = units.get(inp.ref)
                if (
                    source_unit is not None
                    and cand_unit is not None
                    and cand_unit != source_unit
                ):
                    findings.append(
                        (
                            f"stages[{stage.id}]",
                            f"replaceLowestInput source {source!r} ({source_unit}) is "
                            f"incompatible with candidate {inp.ref!r} ({cand_unit}); "
                            "no implicit conversion.",
                        )
                    )
    return findings


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    target = spec.params["target"]
    source = spec.params["source"]
    tie_policy = spec.params.get("tiePolicy", "replaceFirst")

    target_stage = ctx.policy.stages[target]
    if target_stage.operator != "weightedAverage":
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=replaceLowestInput: target {target!r} must be "
            "a weightedAverage stage."
        )

    # Resolve the source first so its missing state follows the operator's policy.
    src_resolved = resolve_refs(ctx, spec, [source])
    _, _mds, terminal = apply_missing(ctx, spec, src_resolved)
    if terminal is not None:
        return terminal
    source_value = src_resolved[0].value

    # Resolve the target state before reading its candidates (V1 restriction):
    # the target must be in state=value. A validated policy always reaches this
    # point with a value target, but the guard keeps the operator fail-closed.
    _, target_state, target_reason = ctx.resolve_ref(target)
    if target_state != VALUE:
        raise MissingInputError(
            f"stages[{spec.id}].operator=replaceLowestInput: target {target!r} is not "
            f"in state=value ({target_state}"
            f"{f': {target_reason}' if target_reason else ''}); candidates cannot be read."
        )

    candidate_refs = [inp.ref for inp in target_stage.inputs]
    weights = {inp.ref: (inp.weight or DZERO) for inp in target_stage.inputs}

    candidate_values = {}
    for ref in candidate_refs:
        value, state, reason = ctx.resolve_ref(ref)
        if state != VALUE:
            raise MissingInputError(
                f"stages[{spec.id}].operator=replaceLowestInput: target candidate {ref!r} "
                f"is not present ({state}: {reason or 'missing'})."
            )
        candidate_values[ref] = value

    values = list(candidate_values.values())
    require_same_unit(values + [source_value], spec.operator, spec.id)

    if not candidate_values:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=replaceLowestInput: target {target!r} declares no inputs."
        )

    # Select exactly one candidate: the lowest present value. On ties the
    # tiePolicy decides which occurrence is replaced.
    minima = [ref for ref in candidate_refs if candidate_values[ref].value == min(
        candidate_values[r].value for r in candidate_refs
    )]
    if tie_policy == "replaceFirst":
        selected_ref = minima[0]
    else:  # replaceLast
        selected_ref = minima[-1]

    original_value = candidate_values[selected_ref]

    def _recompute():
        total = DZERO
        for ref in candidate_refs:
            value = source_value.value if ref == selected_ref else candidate_values[ref].value
            total += value * (weights[ref] or DZERO)
        return total

    result = run(_recompute)
    output = AcademicValue(result, original_value.unit)

    operator_data = {
        "candidateRefs": list(candidate_refs),
        "selectedRef": selected_ref,
        "originalValue": original_value.to_dict(),
        "replacementValue": source_value.to_dict(),
        "tiePolicy": tie_policy,
        "weights": {ref: decimal_str(weights[ref]) for ref in candidate_refs},
        "recalculatedOutput": output.to_dict(),
    }
    decisions = [
        f"replaceLowestInput: selected {selected_ref} (min {decimal_str(original_value.value)}) "
        f"replaced with {source}={decimal_str(source_value.value)}"
    ]
    return EvalResult(
        value=output,
        state=VALUE,
        decisions=decisions,
        operator_data=operator_data,
    )


spec = OperatorSpec(
    name="replaceLowestInput",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "source": {"type": "string"},
            "tiePolicy": {"enum": ["replaceFirst", "replaceLast"]},
        },
        "required": ["target", "source", "tiePolicy"],
        "additionalProperties": False,
    },
    allowed_phases=("adjustment",),
    accepted_input_units=("points", "percent", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "pending", "notApplicable"),
    evaluate=_evaluate,
    referenced_refs=referenced_refs,
    min_inputs=0,
    max_inputs=0,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Replaces the lowest present input of a weightedAverage target with a source value and recomputes the average.",
)
