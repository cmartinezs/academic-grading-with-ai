"""Closed registries for operators and conditions (V1).

The catalogs are closed: they are built from the fixed set of operator and
condition implementations in this package. There is deliberately no public
registration API, so future additions go through a schema major-version bump.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .conditions import condition_names
from .errors import UnsupportedConditionError, UnsupportedOperatorError
from .models import ROUNDING_MODES
from .operators.base import OperatorSpec
from .operators import (
    additive_bonus,
    cap,
    floor,
    piecewise_linear_scale,
    replace_lowest_input,
    round as round_op,
    sum as sum_op,
    weighted_average,
)

OPERATOR_SPECS: Mapping[str, OperatorSpec] = {
    spec.name: spec
    for spec in (
        weighted_average.spec,
        sum_op.spec,
        piecewise_linear_scale.spec,
        additive_bonus.spec,
        replace_lowest_input.spec,
        cap.spec,
        floor.spec,
        round_op.spec,
    )
}

OPERATOR_NAMES: tuple[str, ...] = tuple(OPERATOR_SPECS.keys())


def operator_spec(name: str) -> Optional[OperatorSpec]:
    return OPERATOR_SPECS.get(name)


def require_operator(name: str) -> OperatorSpec:
    spec = OPERATOR_SPECS.get(name)
    if spec is None:
        raise UnsupportedOperatorError(f"Unsupported operator: {name!r}")
    return spec


def require_condition(name: str) -> None:
    if name not in condition_names():
        raise UnsupportedConditionError(f"Unsupported condition: {name!r}")


def available_operators() -> tuple[str, ...]:
    return OPERATOR_NAMES


def available_conditions() -> tuple[str, ...]:
    return condition_names()


def available_rounding_modes() -> tuple[str, ...]:
    return ROUNDING_MODES
