"""Small shared helpers."""

from __future__ import annotations

import re

_PATTERN_CHILEAN_RUT = re.compile(r"(?:\d{1,2}\.\d{3}\.\d{2,3}|\d{6,8})-[\dKk]")
_PATTERN_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_value(value: object, keep: int = 3) -> str:
    """Return a masked rendering of a sensitive value (never the full value)."""
    text = str(value)
    if len(text) <= keep + 3:
        return text[:keep] + "***"
    return text[:keep] + "***" + text[-2:]


def mask_path(path: str) -> str:
    """Mask PII that appears inside a path (RUT-shaped or email-shaped segments)."""
    masked = _PATTERN_CHILEAN_RUT.sub(lambda match: mask_value(match.group(0)), path)
    masked = _PATTERN_EMAIL.sub(lambda match: mask_value(match.group(0)), masked)
    return masked


def sanitize_text(text: str) -> str:
    """Mask PII anywhere inside a message (paths, identifiers, addresses)."""
    return mask_path(text)
