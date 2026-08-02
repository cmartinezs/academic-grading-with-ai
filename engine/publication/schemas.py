"""JSON Schema registry and validation for publication snapshot contracts.

Uses JSON Schema Draft 2020-12 via the pinned ``jsonschema`` dependency. No
home-grown schema engine: schemas are data files under ``schemas/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .errors import SchemaError

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_VERSION = "1.0.0"

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - documented dependency
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]

# Map of relative snapshot path -> schema filename.
REL_PATH_SCHEMAS: dict[str, str] = {
    "manifest.json": "manifest.schema.json",
    "canonical/section.json": "section.schema.json",
    "canonical/subjects.json": "subjects.schema.json",
    "canonical/assessments.json": "assessments.schema.json",
    "canonical/results.json": "results.schema.json",
    "canonical/policy.json": "policy.schema.json",
    "provenance/source-hashes.json": "source-hashes.schema.json",
    "provenance/engine.json": "engine.schema.json",
    "provenance/migrations.json": "migrations.schema.json",
    "approvals/review.json": "review.schema.json",
    "approvals/publication-approval.json": "publication-approval.schema.json",
}

# C2 canonical documents produced by the grade policy engine (additive).
POLICY_ENGINE_SCHEMAS: dict[str, str] = {
    "canonical/policy.json": "policy-grade-policy.schema.json",
}

# C2 engine artifact schemas live in the grade_policy package (additive).
_GRADE_POLICY_ARTIFACT_SCHEMAS: dict[str, str] = {
    "canonical/outcomes.json": "outcomes",
    "canonical/traces.json": "traces",
}

COMPAT_VIEW_SCHEMA = "compatibility-view.schema.json"
LIFECYCLE_EVENT_SCHEMA = "lifecycle-event.schema.json"

_loaded: dict[str, dict] = {}


def _require_jsonschema() -> None:
    if Draft202012Validator is None:
        raise SchemaError(
            "jsonschema is required for C1 schema validation. "
            "Install the pinned dependency: pip install -r engine/publication/requirements.txt"
        )


def load_schema(name: str) -> dict:
    """Load and cache a JSON schema by file name."""
    _require_jsonschema()
    if name in _loaded:
        return _loaded[name]
    path = SCHEMA_DIR / name
    if not path.exists():
        raise SchemaError(f"Schema file not found: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _loaded[name] = payload
    return payload


def schema_for_relpath(relpath: str, instance=None) -> Optional[dict]:
    """Return the schema for a snapshot document by its relative path.

    ``canonical/policy.json`` is mode-aware: the legacy schema constrains
    ``mode: legacy-effective``, while C2 snapshots select the
    ``grade-policy-effective`` schema. Unknown paths fail closed (None).
    """
    if relpath == "canonical/policy.json" and isinstance(instance, dict):
        if instance.get("mode") == "grade-policy-effective":
            return load_schema(POLICY_ENGINE_SCHEMAS[relpath])
        return load_schema(REL_PATH_SCHEMAS[relpath])
    schema_name = REL_PATH_SCHEMAS.get(relpath)
    if schema_name is not None:
        return load_schema(schema_name)
    artifact = _GRADE_POLICY_ARTIFACT_SCHEMAS.get(relpath)
    if artifact is not None:
        try:
            from ..grade_policy.schemas import select_schema
        except ImportError:  # engine/ on sys.path, packages imported top-level
            from grade_policy.schemas import select_schema

        declared = instance.get("schemaVersion") if isinstance(instance, dict) else None
        if declared is None and isinstance(instance, dict):
            declared = instance.get("traceSchemaVersion")
        return select_schema(artifact, declared or "1.0.0")
    return None


def validate_instance(instance, schema: dict) -> list[str]:
    """Validate an instance against a schema; return a list of error strings."""
    _require_jsonschema()
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker() if FormatChecker is not None else None,
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda e: str(e.absolute_path))
    ]


def validate_document(relpath: str, instance) -> list[str]:
    """Validate a snapshot document by its relative path. Unknown paths fail closed."""
    schema = schema_for_relpath(relpath, instance)
    if schema is None:
        return [f"no schema declared for {relpath}"]
    return validate_instance(instance, schema)


def validate_compatibility_view(instance) -> list[str]:
    return validate_instance(instance, load_schema(COMPAT_VIEW_SCHEMA))


def validate_lifecycle_event(instance) -> list[str]:
    return validate_instance(instance, load_schema(LIFECYCLE_EVENT_SCHEMA))


def require_supported_major(declared: str) -> None:
    """Reject documents whose major schema version is unknown (fail-closed)."""
    if not isinstance(declared, str) or declared.count(".") != 2:
        raise SchemaError(f"Malformed schemaVersion: {declared!r}")
    major = declared.split(".")[0]
    if major != SCHEMA_VERSION.split(".")[0]:
        raise SchemaError(
            f"Unsupported schemaVersion {declared!r}; expected {SCHEMA_VERSION} (major {major})."
        )
