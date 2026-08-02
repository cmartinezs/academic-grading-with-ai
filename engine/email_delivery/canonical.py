"""Canonical JSON serialization and hashing for C3 email delivery.

Reuses the deterministic serialization convention from C1 publication/jsonutil.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional


def serialize(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def serialize_compact(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def encode(payload) -> bytes:
    return serialize(payload).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_hash(payload) -> str:
    return sha256_bytes(encode(payload))


def compute_item_hash(recipient_dict: dict) -> str:
    return compute_hash(recipient_dict)


def compute_preview_hash(plan_core: dict) -> str:
    return compute_hash(plan_core)


def compute_idempotency_key(
    section_id: str,
    publication_id: str,
    student_id: str,
    normalized_recipient: str,
    template_id: str,
    template_version: str,
    intent: str,
) -> str:
    payload = {
        "sectionId": section_id,
        "publicationId": publication_id,
        "studentId": student_id,
        "normalizedRecipient": normalized_recipient,
        "templateId": template_id,
        "templateVersion": template_version,
        "intent": intent,
    }
    return compute_hash(payload)


def compute_identity_projection_hash(
    student_id: str,
    display_name: Optional[str],
    contact_email: str,
) -> str:
    payload = {
        "studentId": student_id,
        "displayName": display_name,
        "contactEmail": contact_email,
    }
    return compute_hash(payload)


def compute_template_hash(template_dict: dict) -> str:
    return compute_hash(template_dict)


def derive_plan_id(preview_hash: str) -> str:
    return "eplan_" + preview_hash[:24]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> str:
    import os
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = encode(payload)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".email-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return sha256_bytes(content)
