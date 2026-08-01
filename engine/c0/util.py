"""Small shared helpers."""

from __future__ import annotations


def mask_value(value: object, keep: int = 3) -> str:
    """Return a masked rendering of a sensitive value (never the full value)."""
    text = str(value)
    if len(text) <= keep + 3:
        return text[:keep] + "***"
    return text[:keep] + "***" + text[-2:]
