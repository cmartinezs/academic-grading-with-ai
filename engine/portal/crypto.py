"""AES-256-GCM encryption primitives for C4.

Uses exclusively ``cryptography.hazmat.primitives.ciphers.aead.AESGCM``.
Never reads global configuration; all inputs are explicit. No fallback to a
hand-rolled cipher and no ECB/CBC/XOR anywhere.
"""

from __future__ import annotations

import base64
import os
import secrets
from typing import Optional

from .canonical import encode
from .errors import CapabilityError

KEY_SIZE_BYTES = 32  # AES-256
NONCE_SIZE_BYTES = 12  # GCM standard 96-bit nonce
OBJECT_ID_SIZE_BYTES = 24  # 192 bits


class CryptoUnavailableError(CapabilityError):
    """The cryptography package is missing or cannot provide AESGCM."""


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise CryptoUnavailableError(
            "cryptography is required for AES-256-GCM encryption."
        ) from exc


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_SIZE_BYTES)


def generate_nonce() -> bytes:
    return secrets.token_bytes(NONCE_SIZE_BYTES)


def generate_object_id() -> str:
    return b64url_encode(os.urandom(OBJECT_ID_SIZE_BYTES))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not text:
        raise CapabilityError("Invalid base64url input.")
    try:
        padded = text + "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise CapabilityError("Invalid base64url input.") from exc


def validate_capability_key(text: str) -> None:
    try:
        raw = b64url_decode(text)
    except CapabilityError:
        raise CapabilityError("Capability key is not valid base64url.") from None
    if len(raw) != KEY_SIZE_BYTES:
        raise CapabilityError(
            f"Capability key must decode to {KEY_SIZE_BYTES} bytes; got {len(raw)}."
        )


def build_canonical_aad(
    release_id: str,
    section_id: str,
    publication_id: str,
    object_id: str,
    portal_view_schema_version: str,
    portal_app_version: str,
) -> bytes:
    payload = {
        "schemaVersion": "1.0.0",
        "releaseId": release_id,
        "sectionId": section_id,
        "publicationId": publication_id,
        "objectId": object_id,
        "portalViewSchemaVersion": portal_view_schema_version,
        "portalAppVersion": portal_app_version,
    }
    return encode(payload)


def encrypt_payload(
    key: bytes,
    nonce: bytes,
    aad: bytes,
    plaintext: bytes,
) -> bytes:
    AESGCM = _aesgcm()
    return AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt_payload(
    key: bytes,
    nonce: bytes,
    aad: bytes,
    ciphertext: bytes,
) -> bytes:
    AESGCM = _aesgcm()
    return AESGCM(key).decrypt(nonce, ciphertext, aad)
