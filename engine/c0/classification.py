"""Data classification policy (C0.2).

Defines the four data classes and whether a class may be versioned in Git.
RESTRICTED and CONFIDENTIAL classes are never versionable.
"""

from __future__ import annotations

from enum import Enum


class DataClass(Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


# (kind, data class, reason)
CLASSIFICATION_GUIDANCE: tuple[tuple[str, DataClass, str], ...] = (
    ("source-code", DataClass.PUBLIC, "program code is public by default"),
    ("generic-documentation", DataClass.PUBLIC, "generic documentation"),
    ("internal-documentation", DataClass.INTERNAL, "operational documentation"),
    ("synthetic-fixtures", DataClass.INTERNAL, "approved fictional fixtures"),
    ("rubric-config", DataClass.INTERNAL, "academic configuration without PII"),
    ("section-config", DataClass.INTERNAL, "structural metadata"),
    ("roster", DataClass.RESTRICTED, "names, identifiers and contacts"),
    ("rut-email", DataClass.RESTRICTED, "personal identifiers"),
    ("submissions", DataClass.RESTRICTED, "student work"),
    ("evidence", DataClass.RESTRICTED, "reviewed evidence"),
    ("individual-results", DataClass.RESTRICTED, "grades and feedback per student"),
    ("smtp-api-secrets", DataClass.RESTRICTED, "credentials and tokens"),
    ("operational-state", DataClass.RESTRICTED, "send state, capabilities, ledgers"),
    ("email-previews-logs", DataClass.RESTRICTED, "email previews and logs"),
)


def is_versionable(data_class: DataClass) -> bool:
    """Whether a data class may live in a Git-versioned zone."""
    return data_class in (DataClass.PUBLIC, DataClass.INTERNAL)


def classify(kind: str) -> DataClass:
    for known, data_class, _reason in CLASSIFICATION_GUIDANCE:
        if kind == known:
            return data_class
    return DataClass.CONFIDENTIAL


def reason_for(kind: str) -> str:
    for known, _data_class, reason in CLASSIFICATION_GUIDANCE:
        if kind == known:
            return reason
    return "unknown kind; classified conservatively as CONFIDENTIAL"
