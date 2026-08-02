"""Deterministic decimal arithmetic for the C2 grade policy engine.

Rules (C2 non-negotiable):

- ``Decimal(str(value))`` is the only conversion entry point; binary float is
  never used as calculation authority.
- All computation runs inside a fixed ``decimal.Context`` (prec=28,
  ROUND_HALF_EVEN) via ``localcontext`` so ambient interpreter state cannot
  change results.
- Percentages are plain percentages (78.4 = 78.4%); weights are fractions
  (0.25 = 25%).
- The sum of weights must equal 1 within an explicit tolerance.
- Rounding only happens in explicit ``round`` stages; no implicit rounding
  when displaying, serializing or converting.
- Serialization uses the canonical decimal string (no exponent, no locale).
"""

from __future__ import annotations

from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    localcontext,
)
from typing import Mapping

# Fixed context used for every engine computation. Rounding inside arithmetic
# (multiplication/division/addition) uses HALF_EVEN; explicit round stages may
# request a different mode.
DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

# Explicit tolerance for "sum of weights == 1".
WEIGHT_SUM_TOLERANCE = Decimal("1e-9")

DZERO = Decimal("0")
DONE = Decimal("1")

ROUND_MODE_MAP = {
    "halfUp": ROUND_HALF_UP,
    "halfEven": ROUND_HALF_EVEN,
    "floor": ROUND_FLOOR,
    "ceil": ROUND_CEILING,
    "truncate": ROUND_DOWN,
}


def to_decimal(value) -> Decimal:
    """Convert an arbitrary scalar to Decimal via ``Decimal(str(value))``.

    Accepts int, str, float, bool, None (rejected). Floats are converted
    through their string representation so ``0.1`` becomes ``Decimal("0.1")``
    and never a binary-float artifact.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Cannot convert {value!r} to Decimal")
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    raise ValueError(f"Cannot convert {value!r} to Decimal")


def to_decimal_opt(value):
    if value is None:
        return None
    return to_decimal(value)


def decimal_str(value: Decimal) -> str:
    """Canonical decimal string: no exponent, no trailing zero artifacts.

    ``Decimal("78.4000")`` -> ``"78.4"``; ``Decimal("1E+3")`` -> ``"1000"``.
    Locale and timezone independent.
    """
    if value.is_nan() or value.is_infinite():
        return str(value)
    return format(value.normalize(), "f")


def is_zero(value: Decimal) -> bool:
    return value.is_zero()


def quantize(value: Decimal, quantum: Decimal, mode: str) -> Decimal:
    try:
        rounding = ROUND_MODE_MAP[mode]
    except KeyError as exc:
        raise ValueError(f"Unknown rounding mode: {mode!r}") from exc
    return value.quantize(quantum, rounding=rounding)


def decimal_from_quantum_parts(value: Decimal, decimal_places: int, mode: str) -> Decimal:
    quantum = Decimal(1).scaleb(-decimal_places)
    return quantize(value, quantum, mode)


def run(fn, *args, **kwargs):
    """Run a callable inside the fixed decimal context (deterministic)."""
    with localcontext(DECIMAL_CONTEXT):
        return fn(*args, **kwargs)
