"""Versioned email template loading and validation for C3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .canonical import compute_template_hash, read_json
from .errors import TemplateError, UnknownPlaceholderError, TemplateHashMismatchError, CRLFInjectionError
from .models import TemplateDocument
from .recipients import check_crlf_injection
from .schemas import TEMPLATE_SCHEMA_V1

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


PLACEHOLDER_RE = __import__('re').compile(r'\{\{([a-zA-Z][a-zA-Z0-9]*)\}\}')


def validate_template_schema(payload: dict) -> list[str]:
    if not HAS_JSONSCHEMA:
        return []
    try:
        jsonschema.validate(payload, TEMPLATE_SCHEMA_V1)
        return []
    except jsonschema.ValidationError as exc:
        return [str(exc.message)]


def extract_placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def load_template(path: Path) -> TemplateDocument:
    payload = read_json(path)
    errors = validate_template_schema(payload)
    if errors:
        raise TemplateError(f"Template schema validation failed: {'; '.join(errors)}")
    subject = payload["subject"]
    try:
        check_crlf_injection(subject)
    except CRLFInjectionError:
        raise CRLFInjectionError("CR/LF in template subject.")
    text_body = payload["textBody"]
    allowed = set(payload["allowedPlaceholders"])
    used_subject = extract_placeholders(subject)
    used_body = extract_placeholders(text_body)
    used = used_subject | used_body
    unknown = used - allowed
    if unknown:
        raise UnknownPlaceholderError(f"Unknown placeholders: {sorted(unknown)}")
    return TemplateDocument(
        schema_version=payload["schemaVersion"],
        template_id=payload["templateId"],
        template_version=payload["templateVersion"],
        intent=payload["intent"],
        subject=subject,
        text_body=text_body,
        allowed_placeholders=tuple(payload["allowedPlaceholders"]),
    )


def load_template_from_dict(payload: dict) -> TemplateDocument:
    errors = validate_template_schema(payload)
    if errors:
        raise TemplateError(f"Template schema validation failed: {'; '.join(errors)}")
    subject = payload["subject"]
    try:
        check_crlf_injection(subject)
    except CRLFInjectionError:
        raise CRLFInjectionError("CR/LF in template subject.")
    text_body = payload["textBody"]
    allowed = set(payload["allowedPlaceholders"])
    used = extract_placeholders(subject) | extract_placeholders(text_body)
    unknown = used - allowed
    if unknown:
        raise UnknownPlaceholderError(f"Unknown placeholders: {sorted(unknown)}")
    return TemplateDocument(
        schema_version=payload["schemaVersion"],
        template_id=payload["templateId"],
        template_version=payload["templateVersion"],
        intent=payload["intent"],
        subject=subject,
        text_body=text_body,
        allowed_placeholders=tuple(payload["allowedPlaceholders"]),
    )


def compute_template_document_hash(template: TemplateDocument) -> str:
    return compute_template_hash(template.to_dict())
