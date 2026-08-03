"""Approval workflow for C3 email delivery.

Approval binds a human reviewer to the exact previewHash of the plan.
No auto-approval. No --force.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .canonical import compute_preview_hash, read_json
from .errors import (
    ApprovalMismatchError,
    AlreadyApprovedError,
    ApprovalError,
    IdentityDriftError,
    NotApprovedError,
    PlanTamperedError,
    SnapshotTerminalError,
)
from .models import ApprovalRecord


SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})


def approve_plan(
    plan_id: str,
    preview_hash: str,
    recipient_count: int,
    actor: str,
    ledger,
    plan_dir: Path,
    identity_store=None,
    lifecycle_ledger=None,
    publication_id: Optional[str] = None,
    confirm_reviewed: bool = False,
    clock=None,
) -> ApprovalRecord:
    if not confirm_reviewed:
        raise ApprovalError("confirm_reviewed is required for approval.")

    if not actor or not actor.strip():
        raise ApprovalMismatchError("actor is required for approval.")
    if "@" in actor:
        raise ApprovalMismatchError("actor must be a non-email audit id.")

    from .plan import verify_plan_bundle
    try:
        verify_plan_bundle(plan_dir)
    except PlanTamperedError as exc:
        raise PlanTamperedError(f"Plan bundle verification failed: {exc}") from exc

    plan_path = plan_dir / "plan.json"
    if not plan_path.exists():
        raise NotApprovedError(f"Plan not found: {plan_dir}")

    plan_dict = read_json(plan_path)
    plan_preview_hash = plan_dict.get("previewHash", "")
    plan_recipient_count = plan_dict.get("recipientCount", 0)

    if plan_preview_hash != preview_hash:
        raise ApprovalMismatchError(
            f"previewHash mismatch: plan has {plan_preview_hash}, provided {preview_hash}"
        )

    if plan_recipient_count != recipient_count:
        raise ApprovalMismatchError(
            f"recipientCount mismatch: plan has {plan_recipient_count}, provided {recipient_count}"
        )

    if lifecycle_ledger is None or publication_id is None:
        raise ApprovalError("lifecycle_ledger and publication_id are required for approval.")

    state = lifecycle_ledger.current_state(publication_id)
    if state in SNAPSHOT_TERMINAL_STATES:
        raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
    if state != "approved":
        raise SnapshotTerminalError(f"Snapshot state is {state}, expected approved.")

    if identity_store is not None:
        _check_identity_drift(plan_dict, identity_store)

    existing = ledger.get_approval(plan_id)
    if existing is not None:
        if existing.preview_hash == preview_hash:
            return existing
        raise ApprovalMismatchError(
            "Plan already approved with a different previewHash."
        )

    approved_at = ""
    if clock is not None:
        approved_at = clock.iso()
    else:
        from datetime import datetime, timezone
        approved_at = datetime.now(timezone.utc).isoformat()

    record = ApprovalRecord(
        plan_id=plan_id,
        preview_hash=preview_hash,
        recipient_count=recipient_count,
        approved_by=actor,
        approved_at=approved_at,
        status="approved",
    )

    ledger.record_approval(record)
    return record


def verify_approval(
    plan_id: str,
    preview_hash: str,
    ledger,
) -> ApprovalRecord:
    record = ledger.get_approval(plan_id)
    if record is None:
        raise NotApprovedError(f"No approval found for plan {plan_id}")
    if record.preview_hash != preview_hash:
        raise ApprovalMismatchError(
            f"Approval previewHash {record.preview_hash} does not match {preview_hash}"
        )
    return record


def _check_identity_drift(plan_dict: dict, identity_store) -> None:
    for recipient in plan_dict.get("recipients", []):
        student_id = recipient.get("studentId")
        stored_hash = recipient.get("identityProjectionHash")
        identity = identity_store.resolve(student_id)
        if identity is None:
            raise IdentityDriftError(f"studentId {student_id} no longer in IdentityStore.")
        email = (identity.contact or {}).get("email", "")
        display_name = identity.display_name or ""
        from .canonical import compute_identity_projection_hash
        current_hash = compute_identity_projection_hash(student_id, display_name, email)
        if current_hash != stored_hash:
            raise IdentityDriftError(
                f"Identity drift for {student_id}: hash changed."
            )
