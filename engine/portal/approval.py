"""Human approval workflow for C4 portal releases.

Approval binds a reviewer to the exact verified release bundle and to the exact
approved, immutable Publication Snapshot that produced it. No auto-approval and
no force path exist. The domain also rejects a falsy confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .canonical import read_json, write_json
from .errors import (
    ApprovalError,
    ApprovalMismatchError,
    AlreadyApprovedError,
    BundleTamperedError,
    IdentityDriftError,
    NotApprovedError,
)
from .models import validate_actor, validate_release_id
from .snapshot import verify_source_snapshot

APPROVAL_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ApprovalRecord:
    release_id: str
    release_hash: str
    object_count: int
    approved_by: str
    approved_at: str
    status: str = "approved"


def _load_plan(plan_dir: Path) -> dict:
    plan_path = Path(plan_dir) / "plan.json"
    if not plan_path.exists():
        raise BundleTamperedError("plan.json missing from release bundle.")
    return read_json(plan_path)


def _verify_bundle(plan_dir: Path) -> dict:
    from .bundle import _recompute_and_compare

    plan_doc = _load_plan(plan_dir)
    _recompute_and_compare(Path(plan_dir), plan_doc)
    return plan_doc


def _check_identity_drift(plan_dir: Path, plan_doc: dict, identity_store) -> None:
    cap_manifest = read_json(Path(plan_dir) / "capability-manifest.json")
    for entry in cap_manifest.get("entries", []):
        student_id = entry["studentId"]
        identity = identity_store.resolve(student_id)
        if identity is None:
            raise IdentityDriftError(f"studentId {student_id} no longer in IdentityStore.")
        display_name = identity.display_name
        contact_email = (identity.contact or {}).get("email", "")
        from .bundle import _identity_projection_hash

        current_hash = _identity_projection_hash(student_id, display_name, contact_email)
        if current_hash != entry.get("identityProjectionHash"):
            raise IdentityDriftError(f"Identity drift for {student_id}: hash changed.")


def approve_release(
    *,
    release_id: str,
    plan_dir: Path,
    actor: str,
    ledger,
    identity_store,
    lifecycle_ledger,
    publication_id: str,
    snapshot_dir: Path,
    confirm_reviewed: bool = False,
    clock=None,
) -> ApprovalRecord:
    validate_release_id(release_id)
    if not confirm_reviewed:
        raise ApprovalError("confirm_reviewed is required for approval.")
    actor = validate_actor(actor)
    if identity_store is None:
        raise ApprovalError("identity_store is required for approval.")
    if lifecycle_ledger is None:
        raise ApprovalError("lifecycle_ledger is required for approval.")

    plan_doc = _verify_bundle(plan_dir)
    if plan_doc.get("releaseId") != release_id:
        raise ApprovalMismatchError("plan releaseId does not match the requested release.")

    from .plan import compute_release_intent_hash

    hosting_profile_hash = _hosting_profile_hash_for(plan_doc)
    expected_intent_hash = compute_release_intent_hash(
        plan_doc["sectionId"],
        plan_doc["publicationId"],
        plan_doc["snapshot"]["contentHash"],
        plan_doc["snapshot"]["reviewHash"],
        plan_doc["snapshot"]["mode"],
        plan_doc["portalAppVersion"],
        hosting_profile_hash,
        plan_doc["portalMode"],
    )
    if release_id != ("prelease_" + expected_intent_hash[:24]):
        raise ApprovalMismatchError("releaseId does not match the release intent.")

    verified_snapshot = verify_source_snapshot(
        snapshot_dir=snapshot_dir,
        section_id=plan_doc["sectionId"],
        publication_id=plan_doc["publicationId"],
        lifecycle_ledger=lifecycle_ledger,
    )
    _assert_snapshot_binding(plan_doc, verified_snapshot)
    if publication_id != plan_doc["publicationId"]:
        raise ApprovalMismatchError("publicationId does not match approved plan.")

    _check_identity_drift(plan_dir, plan_doc, identity_store)

    existing = ledger.get_approval(release_id)
    if existing is not None:
        if (
            existing["releaseHash"] == plan_doc["releaseHash"]
            and existing["objectCount"] == plan_doc["objectCount"]
        ):
            return ApprovalRecord(
                release_id=release_id,
                release_hash=existing["releaseHash"],
                object_count=existing["objectCount"],
                approved_by=existing["approvedBy"],
                approved_at=existing["approvedAt"],
            )
        raise AlreadyApprovedError(
            "Release already approved with different immutable inputs."
        )

    approved_at = (
        clock.iso()
        if clock is not None
        else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    record = ApprovalRecord(
        release_id=release_id,
        release_hash=plan_doc["releaseHash"],
        object_count=plan_doc["objectCount"],
        approved_by=actor,
        approved_at=approved_at,
    )
    ledger.record_approval(record)

    from . import schemas as portal_schemas

    approval_doc = {
        "schemaVersion": APPROVAL_SCHEMA_VERSION,
        "releaseId": release_id,
        "releaseHash": record.release_hash,
        "objectCount": record.object_count,
        "approvedBy": actor,
        "approvedAt": approved_at,
        "confirmation": "confirm-reviewed",
        "status": "approved",
    }
    portal_schemas.validate("approval", approval_doc)
    write_json(Path(plan_dir) / "approval.json", approval_doc)
    return record


def _hosting_profile_hash_for(plan_doc: dict) -> str:
    from .canonical import compute_hash

    profile = plan_doc.get("hostingProfile")
    if not isinstance(profile, dict) or not profile:
        raise BundleTamperedError("plan is missing its hostingProfile binding.")
    return compute_hash(profile)


def verify_approval(release_id: str, release_hash: str, ledger) -> ApprovalRecord:
    record = ledger.get_approval(release_id)
    if record is None:
        raise NotApprovedError(f"No approval found for release {release_id}")
    if record["releaseHash"] != release_hash:
        raise ApprovalMismatchError("Approval releaseHash does not match release.")
    return ApprovalRecord(
        release_id=release_id,
        release_hash=record["releaseHash"],
        object_count=record["objectCount"],
        approved_by=record["approvedBy"],
        approved_at=record["approvedAt"],
    )


def _assert_snapshot_binding(plan_doc: dict, verified_snapshot) -> None:
    snapshot = plan_doc.get("snapshot", {})
    checks = (
        (verified_snapshot.content_hash, snapshot.get("contentHash")),
        (verified_snapshot.review_hash, snapshot.get("reviewHash")),
        (verified_snapshot.section_id, plan_doc.get("sectionId")),
        (verified_snapshot.publication_id, plan_doc.get("publicationId")),
        (verified_snapshot.snapshot_mode, snapshot.get("mode")),
    )
    if any(actual != expected for actual, expected in checks):
        raise BundleTamperedError(
            "Publication Snapshot no longer matches the approved release plan."
        )
