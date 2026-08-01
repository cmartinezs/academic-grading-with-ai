"""Opaque ids and safe section/publication identifiers (C1)."""

from __future__ import annotations

import hashlib
import re
import secrets

from .errors import InvalidPublicationIdError, InvalidSectionIdError

PUBLICATION_ID_PREFIX = "pub_"
PUBLICATION_ID_ENTROPY_BYTES = 16  # 128 bits

_SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PUBLICATION_RE = re.compile(r"^pub_[A-Za-z0-9]{1,64}$")
_STUDENT_ID_RE = re.compile(r"^stu_[A-Za-z0-9]{1,64}$")


def generate_publication_id(existing: set[str] | None = None) -> str:
    """Generate a random opaque publication id (pub_ + 128 bits)."""
    existing = existing or set()
    while True:
        candidate = PUBLICATION_ID_PREFIX + secrets.token_hex(PUBLICATION_ID_ENTROPY_BYTES)
        if candidate not in existing:
            return candidate


def validate_publication_id(publication_id: str) -> str:
    """Validate an opaque publication id (fail-closed on unsafe values)."""
    if not isinstance(publication_id, str) or not _PUBLICATION_RE.match(publication_id):
        raise InvalidPublicationIdError(f"Invalid publicationId: {publication_id!r}")
    return publication_id


def validate_section_id(section_id: str) -> str:
    """Validate a section id as a safe single path segment.

    The section code is not PII but must never be able to escape its namespace.
    """
    if not isinstance(section_id, str) or not _SECTION_RE.match(section_id):
        raise InvalidSectionIdError(f"Invalid sectionId: {section_id!r}")
    if section_id in (".", ".."):
        raise InvalidSectionIdError(f"Invalid sectionId: {section_id!r}")
    return section_id


def attempt_id(section_id: str, assessment_id: str, student_id: str) -> str:
    """Stable, deterministic attempt id within a snapshot.

    Reproducible across rebuilds with the same inputs.
    """
    digest = hashlib.sha256(
        f"{section_id}|{assessment_id}|{student_id}".encode("utf-8")
    ).hexdigest()
    return "att_" + digest[:16]


def validate_student_id(student_id: str) -> str:
    if not isinstance(student_id, str) or not _STUDENT_ID_RE.match(student_id):
        raise ValueError(f"Invalid opaque studentId: {student_id!r}")
    return student_id
