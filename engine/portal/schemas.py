"""JSON Schema loading and validation for C4 portal contracts."""

from __future__ import annotations

import json
from pathlib import Path

from .errors import SchemaValidationError

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

_SCHEMA_REL = {
    "student-portal-view": "student-portal-view-v1.schema.json",
    "release-plan": "release-plan-v1.schema.json",
    "hosting-profile": "hosting-profile-v1.schema.json",
    "approval": "approval-v1.schema.json",
    "capability-manifest": "capability-manifest-v1.schema.json",
    "receipt": "receipt-v1.schema.json",
    "public-bundle-manifest": "public-bundle-manifest-v1.schema.json",
}

_LOADED: dict[str, dict] = {}


def load_schema(name: str) -> dict:
    if name not in _SCHEMA_REL:
        raise SchemaValidationError(f"Unknown portal schema: {name!r}")
    if name in _LOADED:
        return _LOADED[name]
    path = SCHEMAS_DIR / _SCHEMA_REL[name]
    _LOADED[name] = json.loads(path.read_text(encoding="utf-8"))
    return _LOADED[name]


def validate(name: str, document: dict) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise SchemaValidationError(
            "jsonschema is required for portal contract validation."
        ) from exc
    schema = load_schema(name)
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(
            f"{name} failed schema validation: {exc.message}"
        ) from exc


def validate_optional(name: str, document) -> bool:
    """Return True when the document validates, False otherwise (no raise)."""
    try:
        validate(name, document)
        return True
    except SchemaValidationError:
        return False
