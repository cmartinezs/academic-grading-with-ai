"""Versioned JSON Schemas for C2 policy documents and engine artifacts.

Selection rule: the loader reads the ``schemaVersion`` field of the document
and returns the matching schema. Unknown or newer major versions are rejected
(fail-closed) rather than guessed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from ..errors import SchemaValidationError

_SCHEMAS_DIR = Path(__file__).parent

POLICY_SCHEMAS: Mapping[str, dict] = {
    "1.0.0": json.loads((_SCHEMAS_DIR / "policy.schema.json").read_text(encoding="utf-8")),
}

OUTCOMES_SCHEMAS: Mapping[str, dict] = {
    "1.0.0": json.loads((_SCHEMAS_DIR / "outcomes.schema.json").read_text(encoding="utf-8")),
}

TRACES_SCHEMAS: Mapping[str, dict] = {
    "1.0.0": json.loads((_SCHEMAS_DIR / "traces.schema.json").read_text(encoding="utf-8")),
}


def select_schema(kind: str, schema_version: str) -> dict:
    table = {"policy": POLICY_SCHEMAS, "outcomes": OUTCOMES_SCHEMAS, "traces": TRACES_SCHEMAS}.get(
        kind
    )
    if table is None:
        raise SchemaValidationError(f"Unknown schema kind: {kind!r}")
    schema = table.get(schema_version)
    if schema is None:
        raise SchemaValidationError(
            f"No {kind} schema for schemaVersion {schema_version!r}; "
            "supported versions: " + ", ".join(sorted(table))
        )
    return schema


def available_policy_versions() -> tuple[str, ...]:
    return tuple(sorted(POLICY_SCHEMAS))


def policy_schema_version_default() -> str:
    return sorted(POLICY_SCHEMAS)[-1]
