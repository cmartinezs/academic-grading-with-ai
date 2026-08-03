"""Human approval workflow for C3 email delivery.

Approval binds a reviewer to the exact, verified private plan and to the exact
approved Publication Snapshot that produced it.  No auto-approval and no
force path exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import (
    ApprovalMismatchError,
    ApprovalError,
    IdentityDriftError,
    NotApprovedError,
    PlanTamperedError,
    SchemaValidationError,
    TemplateHashMismatchError,
)
from .models import ApprovalRecord
from .recipients import normalize_email


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
    snapshot_dir: Optional[Path] = None,
) -> ApprovalRecord:
    if not confirm_reviewed:
        raise ApprovalError("confirm_reviewed is required for approval.")
    if not actor or not actor.strip():
        raise ApprovalMismatchError("actor is required for approval.")
    if "@" in actor:
        raise ApprovalMismatchError("actor must be a non-email audit id.")
    if snapshot_dir is None:
        raise ApprovalError("snapshot_dir is required for approval.")
    if lifecycle_ledger is None or publication_id is None:
        raise ApprovalError(
            "lifecycle_ledger and publication_id are required for approval."
        )

    from .lifecycle import verify_email_source_snapshot
    from .plan import verify_plan_bundle

    try:
        verified_plan = verify_plan_bundle(Path(plan_dir))
    except (PlanTamperedError, SchemaValidationError) as exc:
        raise PlanTamperedError("Plan bundle verification failed.") from exc

    plan_dict = verified_plan.plan_dict
    if verified_plan.plan_id != plan_id:
        raise ApprovalMismatchError("planId mismatch.")
    if verified_plan.preview_hash != preview_hash:
        raise ApprovalMismatchError("previewHash mismatch.")
    if verified_plan.recipient_count != recipient_count:
        raise ApprovalMismatchError("recipientCount mismatch.")

    verified_snapshot = verify_email_source_snapshot(
        snapshot_dir=Path(snapshot_dir),
        section_id=plan_dict["sectionId"],
        publication_id=plan_dict["publicationId"],
        lifecycle_ledger=lifecycle_ledger,
    )
    _assert_snapshot_binding(plan_dict, verified_snapshot)
    if publication_id != plan_dict["publicationId"]:
        raise ApprovalMismatchError("publicationId does not match approved plan.")

    try:
        ledger.register_template_version(
            plan_dict["templateId"],
            plan_dict["templateVersion"],
            plan_dict["templateHash"],
        )
    except TemplateHashMismatchError as exc:
        raise PlanTamperedError("Template registry mismatch.") from exc

    if identity_store is None:
        raise ApprovalError("identity_store is required for approval.")
    _check_identity_drift(plan_dict, identity_store)

    existing = ledger.get_approval(plan_id)
    if existing is not None:
        if (
            existing.preview_hash == preview_hash
            and existing.recipient_count == recipient_count
        ):
            return existing
        raise ApprovalMismatchError(
            "Plan already approved with different immutable inputs."
        )

    approved_at = (
        clock.iso()
        if clock is not None
        else datetime.now(timezone.utc).isoformat()
    )
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


def verify_approval(plan_id: str, preview_hash: str, ledger) -> ApprovalRecord:
    record = ledger.get_approval(plan_id)
    if record is None:
        raise NotApprovedError(f"No approval found for plan {plan_id}")
    if record.preview_hash != preview_hash:
        raise ApprovalMismatchError("Approval previewHash does not match plan.")
    return record


def _assert_snapshot_binding(plan_dict: dict, verified_snapshot) -> None:
    checks = (
        (verified_snapshot.content_hash, plan_dict.get("snapshotContentHash")),
        (verified_snapshot.review_hash, plan_dict.get("snapshotReviewHash")),
        (verified_snapshot.section_id, plan_dict.get("sectionId")),
        (verified_snapshot.publication_id, plan_dict.get("publicationId")),
        (verified_snapshot.snapshot_mode, plan_dict.get("snapshotMode")),
    )
    if any(actual != expected for actual, expected in checks):
        raise PlanTamperedError(
            "Publication Snapshot no longer matches the approved email plan."
        )


def _check_identity_drift(plan_dict: dict, identity_store) -> None:
    from .canonical import compute_identity_projection_hash

    for recipient in plan_dict.get("recipients", []):
        student_id = recipient.get("studentId")
        identity = identity_store.resolve(student_id)
        if identity is None:
            raise IdentityDriftError(
                f"studentId {student_id} no longer in IdentityStore."
            )
        email = (identity.contact or {}).get("email", "")
        display_name = identity.display_name or ""
        try:
            normalized = normalize_email(email)
        except Exception as exc:
            raise IdentityDriftError(
                f"Identity contact is invalid for {student_id}."
            ) from exc
        current_hash = compute_identity_projection_hash(
            student_id, display_name, normalized
        )
        if current_hash != recipient.get("identityProjectionHash"):
            raise IdentityDriftError(
                f"Identity drift for {student_id}: hash changed."
            )
