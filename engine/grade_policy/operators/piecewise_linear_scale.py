"""piecewiseLinearScale: map a value across ordered breakpoints.

Contract (C2-GRADE-POLICY-CONTRACT.md §6):

- ``inputs``: exactly one ref;
- ``params.breakpoints``: ``[{"x": "...", "y": "..."}]`` with ``x`` strictly
  increasing (at least two breakpoints; duplicates rejected);
- ``params.outputUnit``: explicit output unit (the only operator that converts
  unit);
- ``params.outsideRange``: ``clamp`` | ``reject`` (never implicit).

Runtime behavior:

- deterministic linear interpolation between breakpoints;
- ``clamp`` clamps out-of-range inputs only when ``outsideRange == clamp``;
- ``reject`` raises a typed ``OutOfRangeError`` for out-of-range inputs;
- exact behavior at breakpoints (``x == breakpoint`` yields its ``y``).
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..decimal import DZERO, Decimal, run
from ..errors import OutOfRangeError, SchemaValidationError, UnitMismatchError
from ..models import AcademicValue, EvalResult, MissingDecision, Policy, ResolvedInput, StageSpec
from .base import (
    VALUE,
    OperatorSpec,
    expected_unit,
    missing_policy_for,
    raise_missing,
    resolve_inputs,
    terminal_result,
)


def resolve_output_unit(
    stage: StageSpec, units: Mapping[str, Optional[str]]
) -> Optional[str]:
    return stage.params.get("outputUnit")


def semantic_validate(
    stage: StageSpec, policy: Policy, units: Mapping[str, Optional[str]]
) -> Sequence[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    path = f"stages[{stage.id}]"
    if len(stage.inputs) != 1:
        findings.append((path, "piecewiseLinearScale requires exactly one input."))
    output_unit = stage.params.get("outputUnit")
    if output_unit is None:
        findings.append(
            (path, "piecewiseLinearScale requires an explicit params.outputUnit; the output unit must not be guessed.")
        )
    elif output_unit not in ("percent", "points", "grade", "scalar", "level"):
        findings.append((path, f"piecewiseLinearScale params.outputUnit {output_unit!r} unknown."))
    outside = stage.params.get("outsideRange")
    if outside is None:
        findings.append(
            (path, "piecewiseLinearScale requires an explicit params.outsideRange (clamp|reject); never implicit.")
        )
    elif outside not in ("clamp", "reject"):
        findings.append((path, f"piecewiseLinearScale params.outsideRange {outside!r} unknown."))
    breakpoints = stage.params.get("breakpoints")
    if not breakpoints or len(breakpoints) < 2:
        findings.append((path, "piecewiseLinearScale requires at least two breakpoints."))
    else:
        last_x = None
        seen = set()
        for i, bp in enumerate(breakpoints):
            if not isinstance(bp, dict) or "x" not in bp or "y" not in bp:
                findings.append((path, f"breakpoint {i} must be {{'x', 'y'}}."))
                continue
            try:
                x = Decimal(str(bp["x"]))
                y = Decimal(str(bp["y"]))
            except Exception:
                findings.append((path, f"breakpoint {i} x/y must be valid decimals."))
                continue
            key = str(x)
            if key in seen:
                findings.append((path, f"piecewiseLinearScale has a duplicate x breakpoint at {key}."))
            seen.add(key)
            if last_x is not None and x <= last_x:
                findings.append(
                    (path, "piecewiseLinearScale x breakpoints must be strictly increasing.")
                )
            last_x = x
    return findings


def _scale(spec: StageSpec, x: Decimal) -> Decimal:
    breakpoints: Sequence[dict] = spec.params.get("breakpoints", [])
    if not breakpoints or len(breakpoints) < 2:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: at least two breakpoints required."
        )
    points = []
    for bp in breakpoints:
        try:
            points.append((Decimal(str(bp["x"])), Decimal(str(bp["y"]))))
        except Exception as exc:
            raise SchemaValidationError(
                f"stages[{spec.id}].operator=piecewiseLinearScale: invalid breakpoint {bp!r}."
            ) from exc
    for i in range(1, len(points)):
        if points[i][0] <= points[i - 1][0]:
            raise SchemaValidationError(
                f"stages[{spec.id}].operator=piecewiseLinearScale: x breakpoints must be strictly increasing."
            )

    lo_x, lo_y = points[0]
    hi_x, hi_y = points[-1]

    if x <= lo_x:
        return lo_y
    if x >= hi_x:
        return hi_y
    result = lo_y
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 < x <= x1:
            if x1 == x0:
                result = y1
            else:
                t = (x - x0) / (x1 - x0)
                result = y0 + t * (y1 - y0)
            break
    return run(lambda: result)


def _check_outside(spec: StageSpec, x: Decimal) -> None:
    breakpoints: Sequence[dict] = spec.params.get("breakpoints", [])
    if not breakpoints:
        return
    first_x = Decimal(str(breakpoints[0]["x"]))
    last_x = Decimal(str(breakpoints[-1]["x"]))
    if x < first_x or x > last_x:
        outside = spec.params.get("outsideRange")
        if outside == "reject":
            raise OutOfRangeError(
                f"stages[{spec.id}].operator=piecewiseLinearScale: input {x} is outside "
                f"the breakpoint range [{first_x}, {last_x}] and outsideRange=reject."
            )


def _evaluate(ctx, spec: StageSpec) -> EvalResult:
    resolved = resolve_inputs(ctx, spec)
    inp: ResolvedInput = resolved[0]
    if inp.state != VALUE:
        policy = missing_policy_for(spec)
        if policy == "fail":
            raise_missing(spec, [inp])
        if policy == "pending":
            return terminal_result(spec, [inp], "pending", "required input is missing")
        if policy == "notApplicable":
            return terminal_result(spec, [inp], "notApplicable", "required input is missing")
        if policy == "zero":
            # The zero is created in the *input* ref's expected unit, never in
            # params.outputUnit: piecewiseLinearScale is the only converting
            # operator, so the missing input is a zero on the input scale that
            # then flows through the breakpoints to the output unit.
            input_unit = expected_unit(ctx, inp.ref)
            if input_unit is None:
                raise UnitMismatchError(
                    f"stages[{spec.id}].operator={spec.operator}: cannot determine "
                    "the input unit for a zero backfill; declare the input unit in "
                    "the policy (assessmentUnits or an upstream stage unit)."
                )
            output_unit = spec.params.get("outputUnit")
            if output_unit is None:
                raise SchemaValidationError(
                    f"stages[{spec.id}].operator=piecewiseLinearScale: params.outputUnit required."
                )
            zero_value = AcademicValue(DZERO, input_unit)
            zero = ResolvedInput(ref=inp.ref, value=zero_value, state=VALUE)
            mds = [
                MissingDecision(
                    ref=inp.ref,
                    reason=inp.reason or "input absent",
                    policy="zero",
                    original_weight=None,
                    effective_weight=None,
                    resulting_state=VALUE,
                )
            ]
            # Range check runs before scaling: reject raises OutOfRangeError;
            # clamp lets _scale produce the corresponding extreme.
            _check_outside(spec, zero_value.value)
            result = _scale(spec, zero_value.value)
            return EvalResult(
                AcademicValue(result, output_unit),
                state=VALUE,
                missing_decisions=mds,
            )
        from ..errors import MissingPolicyError

        raise MissingPolicyError(
            f"stages[{spec.id}].operator={spec.operator}: missingPolicy {policy!r} is not "
            "implemented for piecewiseLinearScale."
        )

    value = inp.value
    output_unit = spec.params.get("outputUnit")
    if output_unit is None:
        raise SchemaValidationError(
            f"stages[{spec.id}].operator=piecewiseLinearScale: params.outputUnit required."
        )

    _check_outside(spec, value.value)
    result = _scale(spec, value.value)
    return EvalResult(AcademicValue(result, output_unit), state=VALUE)


spec = OperatorSpec(
    name="piecewiseLinearScale",
    version="1.0.0",
    min_engine_version="0.2.0",
    params_schema={
        "type": "object",
        "properties": {
            "outputUnit": {"enum": ["percent", "points", "grade", "scalar", "level"]},
            "breakpoints": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                        "y": {"type": ["number", "string"], "pattern": "^-?[0-9]+(\\.[0-9]+)?$"},
                    },
                    "required": ["x", "y"],
                    "additionalProperties": False,
                },
            },
            "outsideRange": {"enum": ["clamp", "reject"]},
        },
        "required": ["outputUnit", "breakpoints", "outsideRange"],
        "additionalProperties": False,
    },
    allowed_phases=("conversion",),
    accepted_input_units=("percent", "points", "grade", "scalar", "level"),
    resolve_output_unit=resolve_output_unit,
    allowed_missing_policies=("fail", "zero", "pending", "notApplicable"),
    evaluate=_evaluate,
    min_inputs=1,
    max_inputs=1,
    weight_rule="forbidden",
    semantic_validate=semantic_validate,
    description="Piecewise linear mapping of the input value to an explicit output scale.",
)
