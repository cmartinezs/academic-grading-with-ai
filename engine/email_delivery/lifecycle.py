"""Lifecycle checks for C3 email delivery.

Verifies snapshot state, identity drift, and approval validity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .canonical import compute_identity_projection_hash, compute_hash, read_json, sha256_file
from .errors import (
    IdentityDriftError,
    PlanTamperedError,
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


def derive_snapshot_mode(snapshot_dir: Path) -> str:
    policy_path = snapshot_dir / "canonical" / "policy.json"
    if not policy_path.exists():
        raise SnapshotTerminalError("canonical/policy.json missing from snapshot — cannot derive snapshotMode")
    policy = read_json(policy_path)
    mode = policy.get("mode")
    if mode not in ("legacy-effective", "grade-policy-effective"):
        raise SnapshotTerminalError(f"Invalid snapshot mode in canonical/policy.json: {mode!r}")
    return mode


class VerifiedSnapshot:
    __slots__ = ("content_hash", "review_hash", "section_id", "publication_id", "snapshot_mode", "lifecycle_state")

    def __init__(self, content_hash: str, review_hash: str, section_id: str,
                 publication_id: str, snapshot_mode: str, lifecycle_state: str):
        self.content_hash = content_hash
        self.review_hash = review_hash
        self.section_id = section_id
        self.publication_id = publication_id
        self.snapshot_mode = snapshot_mode
        self.lifecycle_state = lifecycle_state


def verify_email_source_snapshot(
    snapshot_dir: Path,
    section_id: str,
    publication_id: str,
    lifecycle_ledger=None,
) -> VerifiedSnapshot:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        raise PlanTamperedError("Snapshot manifest.json missing")

    manifest = read_json(manifest_path)
    content_hash = manifest.get("contentHash", "")
    review_hash = manifest.get("reviewHash", "")

    if not content_hash or len(content_hash) != 64:
        raise PlanTamperedError("Snapshot manifest contentHash invalid")

    canonical_dir = snapshot_dir / "canonical"
    if not canonical_dir.exists():
        raise PlanTamperedError("Snapshot canonical/ directory missing")

    policy_path = canonical_dir / "policy.json"
    if not policy_path.exists():
        raise PlanTamperedError("Snapshot canonical/policy.json missing — cannot verify policy mode")

    policy = read_json(policy_path)
    snapshot_mode = policy.get("mode")
    if snapshot_mode not in ("legacy-effective", "grade-policy-effective"):
        raise PlanTamperedError(f"Invalid snapshot mode in canonical/policy.json: {snapshot_mode!r}")

    if lifecycle_ledger is not None:
        state = lifecycle_ledger.current_state(publication_id)
        if state in SNAPSHOT_TERMINAL_STATES:
            raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
        if state != "approved":
            raise SnapshotNotApprovedError(f"Snapshot state is {state}, expected approved.")
        lifecycle_state = state
    else:
        raise SnapshotTerminalError("lifecycle_ledger is required for snapshot verification — fail closed")

    return VerifiedSnapshot(
        content_hash=content_hash,
        review_hash=review_hash,
        section_id=section_id,
        publication_id=publication_id,
        snapshot_mode=snapshot_mode,
        lifecycle_state=lifecycle_state,
    )
