"""weightedAverage: sum of weight*value over resolved inputs.

Missing-policy behavior (fail / zero / excludeAndRenormalize / minimumOutput /
pending / notApplicable) is applied per input. ``zero`` backfills with a zero in
the stage's expected unit; ``excludeAndRenormalize`` drops the absent inputs and
renormalizes the remaining weights; ``minimumOutput`` emits params.minimum;
``pending``/``notApplicable`` produce a non-value, non-finalizable state.

Weight rules (C2 contract §6): every input carries its weight in ``InputRef``
(there is no ``params.weights``), weights are positive and their sum equals 1
within ``WEIGHT_SUM_TOLERANCE`` (validated statically and checked at runtime).
"""

from __future__ import annotations

from typing import Mapping, Optional

from ..decimal import DZERO, WEIGHT_SUM_TOLERANCE, Decimal, decimal_str, run
from ..models import AcademicValue, EvalResult, MissingDecision, ResolvedInput, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    common_output_unit,
    fill_zero,
    minimum_result,
    missing_policy_for,
    raise_missing,
    require_same_unit,
    resolve_inputs,
    split_present,
    terminal_result,
)


def resolve_output_unit(
    stage: StageSpec, units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return common_output_unit(stage, units)


def _renormalize(
    spec: StageSpec,
    present: list[ResolvedInput],
    missing: list[ResolvedInput],
    all_weights_total: Decimal,
) -> EvalResult:
    if not present:
        return terminal_result(
            spec, missing, "pending", "no present inputs after excludeAndRenormalize"
        )
    effective_total = sum((r.weight or DZERO) for r in present)
    if effective_total == 0:
        return terminal_result(spec, missing, "pending", "no present inputs after exclusion")
    renormalized = [(r, (r.weight or DZERO) / effective_total) for r in present]

    mds = [
        MissingDecision(
            ref=m.ref,
            reason=m.reason or "input absent",
            policy="excludeAndRenormalize",
            original_weight=m.weight,
            effective_weight=DZERO,
            total_before=all_weights_total,
            resulting_state="excluded",
        )
        for m in missing
    ]
    decisions = [
        "excludeAndRenormalize: "
        f"priorTotal={decimal_str(all_weights_total)} "
        f"effectiveTotal={decimal_str(effective_total)}"
    ]
    for r, w in renormalized:
        decisions.append(
            f"renormalized {r.ref}: {decimal_str(r.weight or DZERO)} -> {decimal_str(w)}"
        )

    def _avg():
        return sum(r.value.value * w for r, w in renormalized)

    result = run(_avg)
    return EvalResult(
        value=AcademicValue(result, present[0].value.unit),
        decisions=decisions,
        state=VALUE,
        missing_decisions=mds,
    )


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_inputs(ctx, spec)
    present, missing = split_present(resolved)
    policy = missing_policy_for(spec)

    if missing:
        if policy == "fail":
            raise_missing(spec, missing)
        if policy == "pending":
            return terminal_result(spec, missing, "pending", "required input is missing")
        if policy == "notApplicable":
            return terminal_result(spec, missing, "notApplicable", "required input is missing")
        if policy == "minimumOutput":
            return minimum_result(ctx, spec, missing)
        if policy == "excludeAndRenormalize":
            all_weights_total = sum((r.weight or DZERO) for r in resolved)
            return _renormalize(spec, present, missing, all_weights_total)
        # policy == "zero"
        present, zero_mds = fill_zero(ctx, spec, present, missing)
    else:
        zero_mds = []

    require_same_unit([r.value for r in present], spec.operator, spec.id)

    weights = [r.weight or DZERO for r in present]
    total = sum(weights, DZERO)
    if abs(total - 1) > WEIGHT_SUM_TOLERANCE:
        from ..errors import WeightSumError

        raise WeightSumError(
            f"stages[{spec.id}].operator={spec.operator}: weights sum {total} != 1."
        )

    output_unit = present[0].value.unit

    def _sum():
        return sum(v.value.value * w for v, w in zip(present, weights))

    result = run(_sum)
    return EvalResult(
        AcademicValue(result, output_unit),
        state=VALUE,
        missing_decisions=zero_mds,
        decisions=[f"weights sum {decimal_str(total)} within tolerance"],
    )


spec = OperatorSpec(
    name="weightedAverage",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "minimum": {
                "type": "object",
                "required": ["value", "unit"],
                "properties": {
                    "value": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    "unit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    },
    allowed_phases=("aggregation", "conversion"),
    accepted_input_units=("percent", "points", "grade", "scalar"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=(
        "fail",
        "zero",
        "excludeAndRenormalize",
        "minimumOutput",
        "pending",
        "notApplicable",
    ),
    evaluate=_evaluate,
    min_inputs=1,
    max_inputs=None,
    weight_rule="required",
    description="Weighted arithmetic mean of present inputs; weights must be positive and sum to 1.",
)
