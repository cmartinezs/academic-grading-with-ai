"""Opaque student identity management (C0.3).

The internal technical identity is an opaque ``studentId`` never derived from PII.
External identifiers (rut, email, avaUser, ...) live only in the private identity
store under the state root. Logs and reports must never include PII.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

STUDENT_ID_PREFIX = "stu_"
STUDENT_ID_ENTROPY_BYTES = 16  # 128 bits
SCHEMA_VERSION = 1


class IdentityError(Exception):
    """Base identity error."""


class IdentityConflictError(IdentityError):
    """An external identifier is already bound to a different opaque identity."""


def generate_student_id(existing: Optional[Iterable[str]] = None) -> str:
    """Generate a random opaque student id, collision-safe against ``existing``."""
    existing_set = set(existing or ())
    while True:
        candidate = STUDENT_ID_PREFIX + secrets.token_hex(STUDENT_ID_ENTROPY_BYTES)
        if candidate not in existing_set:
            return candidate


@dataclass
class StudentIdentity:
    student_id: str
    external_identifiers: dict[str, str] = field(default_factory=dict)
    display_name: Optional[str] = None
    contact: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "studentId": self.student_id,
            "externalIdentifiers": dict(self.external_identifiers),
            "displayName": self.display_name,
            "contact": dict(self.contact),
        }


class IdentityStore:
    """Persistent, private mapping between external identifiers and opaque ids."""

    def __init__(self, identity_dir: Path):
        self.identity_dir = Path(identity_dir)
        self.records: dict[str, StudentIdentity] = {}
        self._by_external: dict[tuple[str, str], str] = {}
        self.issues: list[str] = []
        self._load()

    @property
    def path(self) -> Path:
        return self.identity_dir / "identity.json"

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_records = payload.get("records", [])
        seen_ids: set[str] = set()
        external_owner: dict[tuple[str, str], str] = {}
        for item in raw_records:
            student_id = item.get("studentId")
            if not student_id:
                self.issues.append("record without studentId")
                continue
            if student_id in seen_ids:
                self.issues.append(f"duplicate studentId: {student_id}")
            seen_ids.add(student_id)
            for kind, value in (item.get("externalIdentifiers") or {}).items():
                if not str(value or "").strip():
                    continue
                key = (kind, str(value))
                previous = external_owner.get(key)
                if previous is not None and previous != student_id:
                    self.issues.append(f"conflict: {kind} is bound to multiple student ids")
                external_owner[key] = student_id
            identity = StudentIdentity(
                student_id=student_id,
                external_identifiers=dict(item.get("externalIdentifiers") or {}),
                display_name=item.get("displayName"),
                contact=dict(item.get("contact") or {}),
            )
            self._register(identity)

    def integrity_issues(self) -> list[str]:
        return list(self.issues)

    def _register(self, identity: StudentIdentity) -> None:
        self.records[identity.student_id] = identity
        for kind, value in identity.external_identifiers.items():
            if value:
                self._by_external[(kind, str(value))] = identity.student_id

    def _save(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "records": [identity.to_dict() for identity in sorted(self.records.values(), key=lambda r: r.student_id)],
        }
        fd, tmp_name = tempfile.mkstemp(dir=str(self.identity_dir), prefix=".identity-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    def resolve_by_external(self, kind: str, value: str) -> Optional[str]:
        return self._by_external.get((kind, str(value)))

    def resolve(self, student_id: str) -> Optional[StudentIdentity]:
        return self.records.get(student_id)

    def all(self) -> list[StudentIdentity]:
        return list(self.records.values())

    def count(self) -> int:
        return len(self.records)

    def ensure(
        self,
        external: Mapping[str, str],
        display_name: Optional[str] = None,
        contact: Optional[Mapping[str, str]] = None,
        dry_run: bool = False,
    ) -> str:
        """Return the opaque id for an external identity, creating it if needed.

        Idempotent and stable across executions. Detects conflicts when an external
        identifier is bound to a different opaque id.
        """
        external = {kind: str(value).strip() for kind, value in (external or {}).items() if str(value or "").strip()}

        bound: dict[str, str] = {}
        for kind, value in external.items():
            student_id = self.resolve_by_external(kind, value)
            if student_id:
                bound[student_id] = bound.get(student_id, kind)

        if len(bound) > 1:
            raise IdentityConflictError("External identifiers resolve to different opaque identities.")

        if bound:
            student_id = next(iter(bound))
            identity = self.records[student_id]
            changed = False
            for kind, value in external.items():
                if kind not in identity.external_identifiers:
                    identity.external_identifiers[kind] = value
                    changed = True
            if display_name and not identity.display_name:
                identity.display_name = display_name
                changed = True
            if contact:
                merged = {**identity.contact, **{k: v for k, v in contact.items() if v}}
                if merged != identity.contact:
                    identity.contact = merged
                    changed = True
            if changed and not dry_run:
                self._save()
            return student_id

        student_id = generate_student_id(self.records.keys())
        identity = StudentIdentity(
            student_id=student_id,
            external_identifiers=external,
            display_name=display_name,
            contact=dict(contact or {}),
        )
        if not dry_run:
            self._register(identity)
            self._save()
        return student_id
