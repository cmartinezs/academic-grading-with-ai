"""Publication lifecycle ledger (append-only, under the state root).

Academic state machine: ``created -> reviewed -> approved`` and terminal
``superseded`` / ``corrected`` / ``revoked``. ``published`` is an operational
receipt event recorded in the same ledger but orthogonal to the academic state:
it never changes the derived state. Receipts therefore stay separated from the
academic state machine.

All reads and the append run under a section-level lock; the whole existing
ledger is re-validated (schema + continuous ``seq``) before any append.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from c0.locking import FileLock

from . import schemas
from .clock import Clock
from .errors import InvalidTransitionError, LedgerError
from .jsonutil import serialize_line

EVENTS = ("created", "reviewed", "approved", "published", "superseded", "corrected", "revoked")

ACADEMIC_EVENTS = ("created", "reviewed", "approved", "superseded", "corrected", "revoked")

TERMINAL_EVENTS = ("superseded", "corrected", "revoked")

NONEXISTENT = "nonexistent"


class LifecycleLedger:
    """Append-only ledger for a section, serialized by a section-level lock."""

    def __init__(self, state_root: Path, section_id: str, clock: Optional[Clock] = None):
        self.section_id = section_id
        self.path = Path(state_root) / "publications" / section_id / "lifecycle-ledger.jsonl"
        self.lock_path = Path(state_root) / "locks" / f"lifecycle-{section_id}.lock"
        self.clock = clock or Clock()

    def read_events(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LedgerError(f"Cannot read lifecycle ledger {self.path}: {exc}") from exc
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise LedgerError(f"Corrupt ledger line in {self.path}: {exc}") from exc
            events.append(event)
        return events

    def _validate_events(self, events: list[dict]) -> None:
        """Every event must validate and ``seq`` must be 1, 2, 3, ... continuous."""
        for index, event in enumerate(events, start=1):
            errors = schemas.validate_lifecycle_event(event)
            if errors:
                raise LedgerError(
                    f"Invalid lifecycle event at line {index}: {errors}"
                )
            if int(event.get("seq", 0)) != index:
                raise LedgerError(
                    f"Lifecycle ledger seq discontinuity at line {index}: "
                    f"expected {index}, got {event.get('seq')}."
                )

    def current_state(self, publication_id: str) -> str:
        """Derive the academic state from the last valid academic event.

        ``published`` receipts never change the state; a publication with no
        events reports ``nonexistent`` (distinct from ``created``).
        """
        last = None
        for event in self.read_events():
            if (
                event.get("publicationId") == publication_id
                and event.get("event") in ACADEMIC_EVENTS
            ):
                last = event
        if last is None:
            return NONEXISTENT
        return str(last.get("event"))

    def has_approved(self, publication_id: str) -> bool:
        """True while the academic state is ``approved`` (never revoked/corrected/superseded)."""
        return self.current_state(publication_id) == "approved"

    def append(
        self,
        event_type: str,
        publication_id: str,
        *,
        actor: Optional[str] = None,
        receipt: Optional[str] = None,
        by_publication_id: Optional[str] = None,
        reason: Optional[str] = None,
        validate_reference: Optional[Callable[[str, str], None]] = None,
    ) -> dict:
        """Validate and append an event under the section lock.

        ``validate_reference`` (mandatory for ``superseded``/``corrected``) is a
        callback ``(by_publication_id, event_type) -> None`` that raises
        ``InvalidTransitionError`` when the referenced publication does not
        exist, is not approved, fails verification or its manifest does not
        declare the matching ``supersedes/correctsPublicationId``.
        """
        if event_type not in EVENTS:
            raise InvalidTransitionError(f"Unknown lifecycle event: {event_type!r}")
        actor = self._sanitize_actor(actor)

        with FileLock(self.lock_path):
            events = self.read_events()
            self._validate_events(events)
            state = self._state_for(events, publication_id)
            self._validate_transition(
                event_type,
                state,
                publication_id=publication_id,
                receipt=receipt,
                by_publication_id=by_publication_id,
                validate_reference=validate_reference,
            )

            seq = len(events) + 1
            event = {
                "schemaVersion": "1.0.0",
                "seq": seq,
                "event": event_type,
                "publicationId": publication_id,
                "actor": actor,
                "at": self.clock.iso(),
            }
            if receipt is not None:
                event["receipt"] = receipt
            if by_publication_id is not None:
                event["byPublicationId"] = by_publication_id
            if reason is not None:
                event["reason"] = reason
            errors = schemas.validate_lifecycle_event(event)
            if errors:
                raise LedgerError(f"Invalid lifecycle event: {errors}")

            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                pass
            with open(self.path, "a", encoding="utf-8", buffering=1) as handle:
                handle.write(serialize_line(event))
                handle.flush()
                os.fsync(handle.fileno())
            return event

    @staticmethod
    def _state_for(events: list[dict], publication_id: str) -> str:
        last = None
        for event in events:
            if (
                event.get("publicationId") == publication_id
                and event.get("event") in ACADEMIC_EVENTS
            ):
                last = event
        if last is None:
            return NONEXISTENT
        return str(last.get("event"))

    @staticmethod
    def _sanitize_actor(actor: Optional[str]) -> str:
        if not actor or not isinstance(actor, str) or not actor.strip():
            raise InvalidTransitionError("actor is required for lifecycle events.")
        actor = actor.strip()
        if "@" in actor:
            raise InvalidTransitionError("actor must be a non-email audit id.")
        cleaned = "".join(ch for ch in actor if ch.isalnum() or ch in "._-")
        if cleaned != actor or len(cleaned) > 64:
            raise InvalidTransitionError("actor must be a sanitized audit id (alnum/._-).")
        return cleaned

    def _validate_transition(
        self,
        event_type: str,
        state: str,
        *,
        publication_id: str,
        receipt: Optional[str],
        by_publication_id: Optional[str],
        validate_reference: Optional[Callable[[str, str], None]],
    ) -> None:
        if event_type == "created":
            if state != NONEXISTENT:
                raise InvalidTransitionError(
                    f"created is only allowed as the initial event for a publication "
                    f"(state={state}); duplicate created rejected."
                )
            return
        if event_type == "reviewed":
            if state != "created":
                raise InvalidTransitionError(f"reviewed requires state created (state={state}).")
            return
        if event_type == "approved":
            if state != "reviewed":
                raise InvalidTransitionError(f"approved requires state reviewed (state={state}).")
            return
        if event_type == "published":
            if state != "approved":
                raise InvalidTransitionError(f"published requires an approved snapshot (state={state}).")
            if not receipt:
                raise InvalidTransitionError("published requires a receipt reference.")
            return
        if event_type in TERMINAL_EVENTS:
            if state != "approved":
                raise InvalidTransitionError(
                    f"{event_type} requires an approved snapshot (state={state}); a "
                    "correction or replacement can only affect a previous snapshot "
                    "after the new publication is approved."
                )
            if event_type == "revoked":
                return
            if not by_publication_id:
                raise InvalidTransitionError(f"{event_type} requires byPublicationId.")
            if by_publication_id == publication_id:
                raise InvalidTransitionError(
                    "A publication cannot supersede/correct itself."
                )
            if validate_reference is None:
                raise InvalidTransitionError(
                    f"{event_type} requires reference validation (byPublicationId "
                    "must exist, be approved, pass verification and declare the "
                    "matching supersedes/correctsPublicationId)."
                )
            validate_reference(by_publication_id, event_type)
            return
        raise InvalidTransitionError(f"Unknown lifecycle event: {event_type!r}")
