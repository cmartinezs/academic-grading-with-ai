"""Lifecycle checks for C3 email delivery.

Verifies snapshot state, identity drift, and approval validity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .canonical import compute_identity_projection_hash, read_json
from .errors import (
    IdentityDriftError,
    SnapshotNotApprovedError,
    SnapshotTerminalError,
)

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})
SNAPSHOT_SENDABLE_STATES = frozenset({"approved"})


def check_snapshot_sendable(lifecycle_ledger, publication_id: str) -> str:
    state = lifecycle_ledger.current_state(publication_id)
    if state in SNAPSHOT_TERMINAL_STATES:
        raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
    if state not in SNAPSHOT_SENDABLE_STATES:
        raise SnapshotNotApprovedError(f"Snapshot state is {state}, expected approved.")
    return state


def check_identity_drift(plan_dict: dict, identity_store) -> list[str]:
    drifts = []
    for recipient in plan_dict.get("recipients", []):
        student_id = recipient.get("studentId")
        stored_hash = recipient.get("identityProjectionHash")
        identity = identity_store.resolve(student_id)
        if identity is None:
            drifts.append(f"studentId {student_id} no longer in IdentityStore")
            continue
        email = (identity.contact or {}).get("email", "")
        display_name = identity.display_name or ""
        current_hash = compute_identity_projection_hash(student_id, display_name, email)
        if current_hash != stored_hash:
            drifts.append(f"Identity drift for {student_id}")
    return drifts


def check_plan_integrity(plan_dir: Path, plan_id: str, preview_hash: str) -> bool:
    plan_path = plan_dir / "plan.json"
    if not plan_path.exists():
        return False
    plan_dict = read_json(plan_path)
    if plan_dict.get("planId") != plan_id:
        return False
    if plan_dict.get("previewHash") != preview_hash:
        return False
    return True
