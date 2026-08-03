"""Canonical JSON serialization, hashing, and durable filesystem helpers for C4.

Reuses the deterministic serialization convention from C1/C3 so that hashes and
AAD are byte-stable and interoperable with the browser app.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


def serialize(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = encode(payload)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".portal-", suffix=".tmp")
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


def write_bytes(path: Path, content: bytes) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".portal-", suffix=".tmp")
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


def fsync_dir(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def chmod_tree(root: Path, dir_mode: int, file_mode: int) -> None:
    root = Path(root)
    for current_path, dirs, files in os.walk(root):
        os.chmod(current_path, dir_mode)
        for name in files:
            os.chmod(Path(current_path) / name, file_mode)
        for name in dirs:
            os.chmod(Path(current_path) / name, dir_mode)


def chmod_tree_readonly(root: Path) -> None:
    for current_path, dirs, files in os.walk(root):
        os.chmod(current_path, 0o555)
        for name in files:
            os.chmod(Path(current_path) / name, 0o444)


def rmtree_readonly(path: Path) -> None:
    """Remove a possibly read-only tree (approved snapshots / deployments)."""
    import shutil

    def _onerror(func, current_path, exc_info):
        os.chmod(current_path, 0o700)
        func(current_path)

    shutil.rmtree(path, onerror=_onerror)


def make_readonly(path: Path) -> None:
    path = Path(path)
    for current_path, dirs, files in os.walk(path):
        os.chmod(current_path, 0o555)
        for name in files:
            os.chmod(Path(current_path) / name, 0o444)
