"""Capability and subject reference generation and validation for C4.

Capability keys are 256-bit random values (one per student, never reused across
publications). Object IDs are 192-bit random values never derived from studentId.
Subject references are opaque random values used by the authenticated contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .crypto import (
    generate_key,
    generate_nonce,
    generate_object_id,
    b64url_encode,
    validate_capability_key,
)
from .errors import CapabilityError


def generate_subject_ref() -> str:
    return b64url_encode(__import__("os").urandom(24))


def generate_subject_nonced_key() -> bytes:
    return generate_nonce()


@dataclass(frozen=True)
class StudentCapability:
    student_id: str
    object_id: str
    key: Optional[bytes]
    nonce: Optional[bytes]
    capability_url: Optional[str]
    subject_ref: Optional[str] = None

    def key_b64url(self) -> str:
        if self.key is None:
            raise CapabilityError("No capability key for this mode.")
        return b64url_encode(self.key)

    def nonce_b64url(self) -> str:
        if self.nonce is None:
            raise CapabilityError("No nonce for this mode.")
        return b64url_encode(self.nonce)


def build_capability_url(base_url: str, publication_id: str, object_id: str, key_b64url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/{publication_id}/{object_id}/#k={key_b64url}"


def validate_object_id(object_id: str) -> None:
    if not isinstance(object_id, str) or len(object_id) < 24:
        raise CapabilityError("Object ID is too short.")
    # Base64url alphabet only; 24 bytes produce exactly 32 chars.
    if len(object_id) != 32:
        raise CapabilityError(f"Object ID must have exactly 32 base64url characters; got {len(object_id)}.")
    for ch in object_id:
        if ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-":
            raise CapabilityError("Object ID contains characters outside base64url.")
