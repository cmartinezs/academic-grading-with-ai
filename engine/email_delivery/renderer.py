"""Deterministic template renderer for C3 email delivery.

V1: text/plain only, placeholder substitution, no code execution.
"""

from __future__ import annotations

import re

from .errors import MissingPlaceholderValueError, CRLFInjectionError
from .models import TemplateDocument
from .recipients import normalize_unicode_nfc, normalize_line_endings, check_crlf_injection

PLACEHOLDER_PATTERN = re.compile(r'\{\{([a-zA-Z][a-zA-Z0-9]*)\}\}')


def render(template: TemplateDocument, values: dict[str, str]) -> tuple[str, str]:
    subject = _substitute(template.subject, values, template.allowed_placeholders)
    body = _substitute(template.text_body, values, template.allowed_placeholders)
    subject = normalize_unicode_nfc(subject)
    body = normalize_unicode_nfc(body)
    body = normalize_line_endings(body)
    try:
        check_crlf_injection(subject)
    except CRLFInjectionError:
        raise CRLFInjectionError("Rendered subject contains CR/LF.")
    return subject, body


def _substitute(text: str, values: dict[str, str], allowed: tuple[str, ...]) -> str:
    allowed_set = set(allowed)

    def replacer(match):
        name = match.group(1)
        if name not in allowed_set:
            from .errors import UnknownPlaceholderError
            raise UnknownPlaceholderError(f"Placeholder {name!r} not in allowedPlaceholders.")
        if name not in values:
            raise MissingPlaceholderValueError(f"Missing value for placeholder {name!r}.")
        return values[name]

    return PLACEHOLDER_PATTERN.sub(replacer, text)


def build_results_block(view_dict: dict) -> str:
    lines = []
    assessments = view_dict.get("assessments", [])
    for a in assessments:
        aid = a.get("assessmentId", "?")
        label = a.get("assessmentLabel", aid)
        status = a.get("status", "")
        score = a.get("score")
        grade = a.get("grade")
        value = a.get("value")
        if value is not None:
            lines.append(f"  {label}: {value}")
        elif grade is not None:
            lines.append(f"  {label}: {grade} ({status})")
        elif score is not None:
            lines.append(f"  {label}: {score} ({status})")
        else:
            lines.append(f"  {label}: {status}")
    return "\n".join(lines)
