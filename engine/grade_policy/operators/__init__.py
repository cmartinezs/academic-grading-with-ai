"""Closed V1 operator catalog."""

from . import (
    additive_bonus,
    cap,
    floor,
    piecewise_linear_scale,
    replace_lowest_input,
    round as round_op,
    sum as sum_op,
    weighted_average,
)
from .base import OperatorReference, OperatorSpec

__all__ = [
    "OperatorReference",
    "OperatorSpec",
    "additive_bonus",
    "cap",
    "floor",
    "piecewise_linear_scale",
    "replace_lowest_input",
    "round_op",
    "sum_op",
    "weighted_average",
]
