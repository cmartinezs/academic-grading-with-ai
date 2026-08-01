"""Publication lifecycle ledger (append-only, under the state root).

The approved snapshot is never modified to change its state. Lifecycle events
are recorded in an append-only, auditable ledger; the current state is derived
from valid events. ``published`` requires a generic receipt reference.
``superseded`` / ``corrected`` must reference an existing approved publication.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from c0.locking import FileLock

from .clock import Clock
from .errors import InvalidTransitionError, LedgerError
from . import schemas
from .jsonutil import serialize_line

EVENTS = ("created", "reviewed", "approved", "published", "superseded", "corrected", "revoked")

TERMINAL_EVENTS = ("superseded", "corrected", "revoked")


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
                import json

                event = json.loads(line)
            except ValueError as exc:
                raise LedgerError(f"Corrupt ledger line in {self.path}: {exc}") from exc
            events.append(event)
        return events

    def current_state(self, publication_id: str) -> str:
        """Derive the current state from the last valid event for the publication."""
        last = None
        for event in self.read_events():
            if event.get("publicationId") == publication_id:
                last = event
        if last is None:
            return "created"
        return str(last.get("event", "created"))

    def has_approved(self, publication_id: str) -> bool:
        """True when the publication reached approved and no terminal event followed."""
        state = self.current_state(publication_id)
        return state == "approved" or state == "published"

    def append(
        self,
        event_type: str,
        publication_id: str,
        *,
        actor: Optional[str] = None,
        receipt: Optional[str] = None,
        by_publication_id: Optional[str] = None,
        reason: Optional[str] = None,
        is_approved: Optional[Callable[[str], bool]] = None,
    ) -> dict:
        if event_type not in EVENTS:
            raise InvalidTransitionError(f"Unknown lifecycle event: {event_type!r}")
        state = self.current_state(publication_id)
        self._validate_transition(
            event_type,
            state,
            receipt=receipt,
            by_publication_id=by_publication_id,
            is_approved=is_approved,
        )

        with FileLock(self.lock_path):
            events = self.read_events()
            seq = max((int(event.get("seq", 0)) for event in events), default=0) + 1
            event = {
                "schemaVersion": "1.0.0",
                "seq": seq,
                "event": event_type,
                "publicationId": publication_id,
                "at": self.clock.iso(),
            }
            if actor is not None:
                event["actor"] = actor
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

    def _validate_transition(
        self,
        event_type: str,
        state: str,
        *,
        receipt: Optional[str],
        by_publication_id: Optional[str],
        is_approved: Optional[Callable[[str], bool]],
    ) -> None:
        if event_type == "created":
            if state != "created":
                raise InvalidTransitionError(f"created is only allowed as the initial event (state={state}).")
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
                raise InvalidTransitionError(f"published requires state approved (state={state}).")
            if not receipt:
                raise InvalidTransitionError("published requires a receipt reference.")
            return
        if event_type in TERMINAL_EVENTS:
            if state not in ("approved", "published"):
                raise InvalidTransitionError(
                    f"{event_type} requires an approved (or published) snapshot "
                    f"(state={state}); a correction or replacement can only affect a "
                    "previous snapshot after the new publication is approved."
                )
            if event_type != "revoked" and not by_publication_id:
                raise InvalidTransitionError(f"{event_type} requires byPublicationId.")
            if event_type != "revoked" and is_approved is not None:
                target_approved = is_approved(by_publication_id)
                if not target_approved:
                    raise InvalidTransitionError(
                        f"{event_type} references {by_publication_id!r} which is not approved."
                    )
            return
        raise InvalidTransitionError(f"Unknown lifecycle event: {event_type!r}")
