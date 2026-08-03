"""C4 release lifecycle orchestration.

Ties together the release bundle, approval, durable ledger, publisher adapters,
and receipts. Every publish re-verifies the snapshot, the approved bundle, and
identity drift immediately before deployment, and publish is at-most-once per
idempotency key.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .approval import _check_identity_drift, approve_release, verify_approval
from .bundle import _recompute_and_compare, prepare_release
from .canonical import read_json, sha256_text
from .errors import (
    IdempotencyConflictError,
    LedgerError,
    NotApprovedError,
    OperationalError,
    StateTransitionError,
)
from .ledger import (
    APPROVED,
    BLOCKED,
    PARTIAL,
    PREPARED,
    PUBLISHED,
    PUBLISHING,
    PURGED,
    REVOKED,
    PortalLedger,
)
from .models import PORTAL_APP_VERSION
from .publisher import publisher_for_mode
from .receipts import publish_receipt, purge_receipt, revoke_receipt
from .snapshot import verify_source_snapshot


def idempotency_key(release_id: str, release_hash: str, hosting_profile_id: str, publisher_type: str) -> str:
    return sha256_text(
        release_id + release_hash + hosting_profile_id + publisher_type
    )


def _plan_doc(plan_dir: Path) -> dict:
    plan = read_json(Path(plan_dir) / "plan.json")
    _recompute_and_compare(Path(plan_dir), plan)
    return plan


def prepare(
    *,
    roots,
    section_id: str,
    publication_id: str,
    snapshot_dir: Path,
    hosting_profile,
    portal_mode: str,
    identity_store,
    lifecycle_ledger,
    ledger: PortalLedger,
) -> dict:
    verified = verify_source_snapshot(snapshot_dir, section_id, publication_id, lifecycle_ledger)
    prepared = prepare_release(
        roots=roots,
        section_id=section_id,
        publication_id=publication_id,
        snapshot_dir=snapshot_dir,
        hosting_profile=hosting_profile,
        portal_mode=portal_mode,
        identity_store=identity_store,
        lifecycle_ledger=lifecycle_ledger,
    )
    existing = ledger.get_release(prepared.release_id)
    if existing is None:
        try:
            ledger.record_release(
                release_id=prepared.release_id,
                release_hash=prepared.release_hash,
                release_intent_hash=prepared.release_intent_hash,
                section_id=section_id,
                publication_id=publication_id,
                snapshot_mode=verified.snapshot_mode,
                portal_mode=portal_mode,
                portal_app_version=PORTAL_APP_VERSION,
                hosting_profile_id=hosting_profile.profile_id,
                object_count=prepared.object_count,
            )
        except LedgerError:
            # A concurrent caller already recorded the release: idempotent no-op.
            pass
    return {
        "releaseId": prepared.release_id,
        "releaseHash": prepared.release_hash,
        "releaseIntentHash": prepared.release_intent_hash,
        "objectCount": prepared.object_count,
        "planDir": str(prepared.plan_dir),
        "capabilities": prepared.capabilities,
    }


def approve(
    *,
    release_id: str,
    plan_dir: Path,
    actor: str,
    ledger: PortalLedger,
    identity_store,
    lifecycle_ledger,
    publication_id: str,
    snapshot_dir: Path,
    confirm_reviewed: bool,
    clock=None,
) -> dict:
    record = approve_release(
        release_id=release_id,
        plan_dir=plan_dir,
        actor=actor,
        ledger=ledger,
        identity_store=identity_store,
        lifecycle_ledger=lifecycle_ledger,
        publication_id=publication_id,
        snapshot_dir=snapshot_dir,
        confirm_reviewed=confirm_reviewed,
        clock=clock,
    )
    return {
        "releaseId": record.release_id,
        "releaseHash": record.release_hash,
        "objectCount": record.object_count,
        "approvedBy": record.approved_by,
        "approvedAt": record.approved_at,
        "status": record.status,
    }


def publish(
    *,
    release_id: str,
    plan_dir: Path,
    publisher_type: str,
    ledger: PortalLedger,
    receipts_dir: Path,
    deployments_root: Path,
    identity_store,
    lifecycle_ledger,
    publication_id: str,
    snapshot_dir: Path,
    confirm_publish: bool,
    clock=None,
) -> dict:
    if not confirm_publish:
        raise OperationalError("confirm_publish is required for publishing.")
    release = ledger.get_release(release_id)
    if release is None:
        raise NotApprovedError(f"Release not recorded: {release_id}")

    plan = _plan_doc(plan_dir)
    if plan["releaseHash"] != release["releaseHash"]:
        raise OperationalError("Plan releaseHash does not match the ledger.")

    if release["status"] == PUBLISHED:
        # Published is terminal for the same releaseHash: idempotent no-op.
        run = ledger.latest_publish_run(release_id)
        receipt = None
        if run is not None and run.get("receiptId"):
            receipt = ledger.get_receipt(run["receiptId"])
        return _publish_summary(release, receipt, (run or {}).get("receiptId"))

    if release["status"] not in (APPROVED, PARTIAL):
        raise StateTransitionError(
            f"Release {release_id} is in state {release['status']}; cannot publish."
        )

    verify_approval(release_id, release["releaseHash"], ledger)

    verified = verify_source_snapshot(
        snapshot_dir, plan["sectionId"], publication_id, lifecycle_ledger
    )
    _assert_snapshot_binding(plan, verified)
    if identity_store is not None:
        _check_identity_drift(plan_dir, plan, identity_store)

    publisher = publisher_for_mode(plan["portalMode"])
    if publisher.publisher_type != publisher_type:
        raise OperationalError(
            f"Requested publisher type {publisher_type!r} does not match portal mode "
            f"{plan['portalMode']!r} ({publisher.publisher_type})."
        )
    profile = publisher._profile_from_plan(plan)
    publisher.preflight(profile, plan_dir, ledger)

    key = idempotency_key(
        release_id, release["releaseHash"], plan["hostingProfileId"], publisher.publisher_type
    )
    try:
        run_id = ledger.begin_publish(
            release_id,
            key,
            plan["hostingProfileId"],
            publisher.publisher_type,
        )
    except IdempotencyConflictError:
        return _settle_idempotent_publish(ledger, release, release_id, key)

    try:
        result = publisher.publish(
            plan_dir=plan_dir,
            plan_doc=plan,
            ledger=ledger,
            receipts_dir=receipts_dir,
            deployments_root=deployments_root,
        )
    except Exception as exc:
        ledger.fail_publish(run_id, release_id)
        raise OperationalError(f"Publish failed; release is now partial: {exc}") from exc

    receipt = publish_receipt(
        receipts_dir=receipts_dir,
        ledger=ledger,
        release_id=release_id,
        release_hash=release["releaseHash"],
        hosting_profile_id=plan["hostingProfileId"],
        publisher_type=publisher.publisher_type,
        object_count=result.object_count,
        deployment_reference=result.deployment_reference,
        artifact_manifest_hash=result.artifact_manifest_hash,
        clock=clock,
    )
    ledger.complete_publish(
        run_id,
        release_id,
        [
            {
                "objectId": entry["objectId"],
                "projectionHash": entry["projectionHash"],
                "artifactHash": entry["artifactHash"],
            }
            for entry in plan["objects"]
        ],
        receipt["receiptId"],
    )
    return _publish_summary(release, receipt, receipt["receiptId"])


def _find_run_for_key(ledger, key: str) -> Optional[dict]:
    import sqlite3

    conn = ledger._connect()
    try:
        row = conn.execute(
            "SELECT * FROM publish_runs WHERE idempotencyKey = ?", (key,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _settle_idempotent_publish(ledger, release: dict, release_id: str, key: str) -> dict:
    """Resolve a claimed idempotency key.

    If the winning run is already published, return its receipt (idempotent
    no-op). If it failed into partial, require reconciliation. Otherwise the
    winner is still in flight: wait briefly for it to settle so a concurrent
    caller gets a deterministic result instead of a spurious error.
    """
    existing = _find_run_for_key(ledger, key)
    if existing is None:
        raise OperationalError("Idempotency conflict with no recorded run.")
    for _ in range(100):
        if existing["state"] == "published":
            receipt = ledger.get_receipt(existing["receiptId"]) if existing.get("receiptId") else None
            return _publish_summary(release, receipt, existing["receiptId"])
        if existing["state"] == "partial":
            raise OperationalError(
                "A previous publish of this release is partial; reconcile before retrying."
            )
        time.sleep(0.01)
        existing = _find_run_for_key(ledger, key)
        if existing is None:
            raise OperationalError("Idempotency conflict with no recorded run.")
    raise OperationalError("Idempotency key still claimed by an in-flight publish.")


def _publish_summary(release: dict, receipt: Optional[dict], receipt_id: str) -> dict:
    return {
        "releaseId": release["releaseId"],
        "releaseHash": release["releaseHash"],
        "status": "published",
        "receiptId": receipt_id,
        "receipt": receipt,
    }


def revoke(
    *,
    release_id: str,
    plan_dir: Path,
    ledger: PortalLedger,
    receipts_dir: Path,
    deployments_root: Path,
    actor: str,
    reason: Optional[str],
    confirm_revoke: bool,
    clock=None,
) -> dict:
    if not confirm_revoke:
        raise OperationalError("confirm_revoke is required for revoking.")
    release = ledger.get_release(release_id)
    if release is None:
        raise OperationalError(f"Release not recorded: {release_id}")
    if release["status"] != PUBLISHED:
        raise StateTransitionError(
            f"Release {release_id} is in state {release['status']}; can only revoke a published release."
        )
    plan = _plan_doc(plan_dir)
    publisher = publisher_for_mode(plan["portalMode"])
    result = publisher.revoke(
        plan_dir=plan_dir,
        plan_doc=plan,
        ledger=ledger,
        receipts_dir=receipts_dir,
        deployments_root=deployments_root,
        actor=actor,
        reason=reason,
    )
    receipt = revoke_receipt(
        receipts_dir=receipts_dir,
        ledger=ledger,
        release_id=release_id,
        actor=actor,
        reason=reason,
        requested_objects=plan["objectCount"],
        removed_objects=result.removed_objects,
        unavailable_objects=result.unavailable_objects,
        clock=clock,
    )
    ledger.transition(release_id, PUBLISHED, REVOKED, "revoked", actor, reason)
    return {"releaseId": release_id, "status": REVOKED, "receipt": receipt}


def purge(
    *,
    release_id: str,
    plan_dir: Path,
    ledger: PortalLedger,
    receipts_dir: Path,
    deployments_root: Path,
    actor: str,
    confirm_purge: bool,
    clock=None,
) -> dict:
    if not confirm_purge:
        raise OperationalError("confirm_purge is required for purging.")
    release = ledger.get_release(release_id)
    if release is None:
        raise OperationalError(f"Release not recorded: {release_id}")
    if release["status"] != REVOKED:
        raise StateTransitionError(
            f"Release {release_id} is in state {release['status']}; can only purge a revoked release."
        )
    plan = _plan_doc(plan_dir)
    publisher = publisher_for_mode(plan["portalMode"])
    result = publisher.purge(
        plan_dir=plan_dir,
        plan_doc=plan,
        ledger=ledger,
        receipts_dir=receipts_dir,
        deployments_root=deployments_root,
        actor=actor,
    )
    receipt = purge_receipt(
        receipts_dir=receipts_dir,
        ledger=ledger,
        release_id=release_id,
        actor=actor,
        removed_objects=result.removed_objects,
        missing_objects=result.missing_objects,
        clock=clock,
    )
    ledger.transition(release_id, REVOKED, PURGED, "purged", actor)
    return {"releaseId": release_id, "status": PURGED, "receipt": receipt}


def status(ledger: PortalLedger, release_id: str) -> dict:
    release = ledger.get_release(release_id)
    if release is None:
        raise OperationalError(f"Release not recorded: {release_id}")
    return {
        "releaseId": release["releaseId"],
        "releaseHash": release["releaseHash"],
        "sectionId": release["sectionId"],
        "publicationId": release["publicationId"],
        "snapshotMode": release["snapshotMode"],
        "portalMode": release["portalMode"],
        "hostingProfileId": release["hostingProfileId"],
        "objectCount": release["objectCount"],
        "status": release["status"],
        "createdAt": release["createdAt"],
        "updatedAt": release["updatedAt"],
        "events": [
            {
                "event": event["event"],
                "actor": event["actor"],
                "reason": event.get("reason"),
                "at": event["at"],
            }
            for event in ledger.lifecycle_events(release_id)
        ],
    }


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
        raise OperationalError(
            "Publication Snapshot no longer matches the approved release plan."
        )
