"""Deterministic canonical JSON serialization for the grade policy engine.

Self-contained copy of the C1 canonical form (UTF-8, ensure_ascii=False,
sorted keys, stable indentation, final newline) so the engine does not depend
on the publication package to compute ``policyHash`` or artifact hashes.
"""

from __future__ import annotations

import hashlib
import json


def serialize(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def encode(payload) -> bytes:
    return serialize(payload).encode("utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
