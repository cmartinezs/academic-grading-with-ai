"""C4 reconciliation.

Compares the actual deployment state against the approved plan and the durable
ledger. A partial release can be completed when every expected object is present;
otherwise it is marked blocked. Every decision is recorded as a reconciliation
event in the ledger.
"""

from __future__ import annotations

from pathlib import Path

from .approval import _verify_bundle
from .canonical import read_json
from .errors import OperationalError, ReconciliationError
from .ledger import (
    APPROVED,
    BLOCKED,
    PARTIAL,
    PUBLISHED,
    PUBLISHING,
    PortalLedger,
)
from .publisher import publisher_for_mode
from .receipts import publish_receipt


def _deployment_dir(publisher, deployments_root: Path, plan_doc: dict) -> Path:
    if publisher.publisher_type == "local-static":
        return publisher._deployment_dir(deployments_root, plan_doc)
    if publisher.publisher_type == "fake-authenticated":
        return publisher._store_dir(deployments_root, plan_doc)
    raise ReconciliationError("Unknown publisher for reconciliation.")


def _deployment_complete(publisher, deployments_root: Path, plan_doc: dict, plan_dir: Path) -> tuple[bool, int]:
    deployment = _deployment_dir(publisher, deployments_root, plan_doc)
    if not deployment.exists():
        return False, 0
    public_manifest = read_json(Path(plan_dir) / "public-bundle" / "manifest.json")
    present = 0
    for entry in public_manifest["objects"]:
        if publisher.publisher_type == "local-static":
            target = deployment / entry["objectId"]
        else:
            from .hosting.fake_authenticated import FakeAuthenticatedPublisher

            cap = read_json(Path(plan_dir) / "capability-manifest.json")
            subject_ref = next(
                (e.get("subjectRef") for e in cap.get("entries", []) if e["objectId"] == entry["objectId"]),
                None,
            )
            target = deployment / f"{subject_ref}.json" if subject_ref else None
        if target is not None and target.exists():
            present += 1
    return present == len(public_manifest["objects"]), present


def diff_deployment(
    *,
    release_id: str,
    plan_dir: Path,
    ledger: PortalLedger,
    deployments_root: Path,
) -> dict:
    """Compare the deployed objects against the approved plan; no state changes."""
    release = ledger.get_release(release_id)
    if release is None:
        raise OperationalError(f"Release not recorded: {release_id}")
    plan_doc = _verify_bundle(Path(plan_dir))
    publisher = publisher_for_mode(plan_doc["portalMode"])
    complete, present = _deployment_complete(publisher, deployments_root, plan_doc, plan_dir)
    public_manifest = read_json(Path(plan_dir) / "public-bundle" / "manifest.json")
    total = len(public_manifest["objects"])
    return {
        "releaseId": release_id,
        "expectedObjects": total,
        "objectsPresent": present,
        "missingObjects": total - present,
        "deploymentComplete": complete,
        "status": release["status"],
    }


def reconcile_release(
    *,
    release_id: str,
    plan_dir: Path,
    ledger: PortalLedger,
    receipts_dir: Path,
    deployments_root: Path,
    actor: str,
    clock=None,
) -> dict:
    release = ledger.get_release(release_id)
    if release is None:
        raise OperationalError(f"Release not recorded: {release_id}")
    status = release["status"]

    if status not in (PARTIAL, PUBLISHING, PUBLISHED):
        raise ReconciliationError(
            f"Release {release_id} is in state {status}; nothing to reconcile."
        )

    plan_doc = _verify_bundle(Path(plan_dir))
    if plan_doc["releaseHash"] != release["releaseHash"]:
        ledger.record_reconciliation_event(
            release_id, "releaseHash mismatch", "blocked", actor
        )
        raise ReconciliationError("Plan releaseHash does not match the ledger.")

    publisher = publisher_for_mode(plan_doc["portalMode"])
    complete, present = _deployment_complete(publisher, deployments_root, plan_doc, plan_dir)

    if status == PUBLISHED:
        if not complete:
            ledger.record_reconciliation_event(
                release_id, f"published but deployment incomplete ({present} objects)",
                "blocked", actor,
            )
            ledger.transition(release_id, PUBLISHED, BLOCKED, "reconcile-blocked", actor)
            return {"releaseId": release_id, "status": BLOCKED,
                    "finding": "published release lost objects", "objectsPresent": present}
        ledger.record_reconciliation_event(release_id, "deployment verified", "ok", actor)
        return {"releaseId": release_id, "status": PUBLISHED, "objectsPresent": present}

    if not complete:
        ledger.record_reconciliation_event(
            release_id, f"deployment incomplete ({present} objects)",
            "blocked", actor,
        )
        ledger.transition(release_id, status, BLOCKED, "reconcile-blocked", actor)
        return {"releaseId": release_id, "status": BLOCKED,
                "finding": "deployment incomplete", "objectsPresent": present}

    ledger.record_reconciliation_event(
        release_id, f"deployment complete ({present} objects)", "publish", actor,
    )
    if status == PARTIAL:
        ledger.transition(release_id, PARTIAL, PUBLISHING, "reconcile-publish", actor)
    run = ledger.latest_publish_run(release_id)
    receipt = publish_receipt(
        receipts_dir=receipts_dir,
        ledger=ledger,
        release_id=release_id,
        release_hash=release["releaseHash"],
        hosting_profile_id=plan_doc["hostingProfileId"],
        publisher_type=publisher.publisher_type,
        object_count=present,
        deployment_reference=str(_deployment_dir(publisher, deployments_root, plan_doc)),
        artifact_manifest_hash=release["releaseHash"],
        clock=clock,
    )
    ledger.complete_publish(
        run["runId"] if run else 0,
        release_id,
        [
            {
                "objectId": entry["objectId"],
                "projectionHash": entry["projectionHash"],
                "artifactHash": entry["artifactHash"],
            }
            for entry in plan_doc["objects"]
        ],
        receipt["receiptId"],
    )
    return {"releaseId": release_id, "status": PUBLISHED, "receipt": receipt,
            "objectsPresent": present}
