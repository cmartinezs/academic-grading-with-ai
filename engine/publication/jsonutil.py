"""Deterministic JSON serialization and hashing (C1)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def serialize(payload) -> str:
    """Serialize to the canonical deterministic form used by C1.

    UTF-8, ensure_ascii=False, sorted keys, stable indentation, final newline.
    Locale and timezone independent.
    """
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def serialize_line(payload) -> str:
    """Compact single-line deterministic JSON for append-only ledger records."""
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


def write_json(path: Path, payload) -> str:
    """Write payload deterministically (atomic via temp file + replace).

    Returns the sha256 of the bytes actually written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = encode(payload)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".pub-", suffix=".tmp")
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


def read_json(path: Path) -> dict:
    import json as _json

    return _json.loads(path.read_text(encoding="utf-8"))


def compute_content_hash(file_hashes: dict[str, str]) -> str:
    """Logical content hash over the canonical representation of declared files.

    Excludes volatile operational metadata (timestamps, approvals, manifest).
    """
    canonical = {rel: {"sha256": hashes} for rel, hashes in sorted(file_hashes.items())}
    return sha256_text(serialize({"files": canonical}))


# provenance/engine.json carries volatile build metadata (builtAt); it is excluded
# from the logical content hash (invariant 13) but still protected per-file by
# manifest.files.
CONTENT_HASH_EXCLUDED = frozenset({"provenance/engine.json"})


def is_content_file(rel: str) -> bool:
    """True for files that participate in the logical contentHash."""
    if rel.startswith("canonical/"):
        return True
    return rel.startswith("provenance/") and rel not in CONTENT_HASH_EXCLUDED
