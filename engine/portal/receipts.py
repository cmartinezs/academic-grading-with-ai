"""Durable receipts for publish, revoke, and purge operations.

Receipts are JSON documents persisted under ``state_root/portal/receipts/`` and
mirrored into the ledger. They never contain capability keys, capability URLs,
studentId mappings, display names, emails, scores, grades, or feedback.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .canonical import write_json
from .errors import LedgerError
from .ledger import utc_now_iso
from . import schemas as portal_schemas

RECEIPT_ID_PREFIX = "rcpt_"


def new_receipt_id() -> str:
    return RECEIPT_ID_PREFIX + secrets.token_urlsafe(16)


def _validate(receipt: dict) -> None:
    portal_schemas.validate("receipt", receipt)


def _write(receipts_dir: Path, ledger, receipt: dict) -> dict:
    _validate(receipt)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    try:
        receipts_dir.chmod(0o700)
    except OSError:
        pass
    path = receipts_dir / f"{receipt['receiptId']}.json"
    write_json(path, receipt)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if ledger is not None:
        ledger.record_receipt(receipt)
    return receipt


def publish_receipt(
    *,
    receipts_dir: Path,
    ledger,
    release_id: str,
    release_hash: str,
    hosting_profile_id: str,
    publisher_type: str,
    object_count: int,
    deployment_reference: str,
    artifact_manifest_hash: str,
    clock=None,
) -> dict:
    now = clock.iso() if clock is not None else utc_now_iso()
    receipt = {
        "receiptId": new_receipt_id(),
        "type": "publish",
        "releaseId": release_id,
        "releaseHash": release_hash,
        "createdAt": now,
        "hostingProfileId": hosting_profile_id,
        "publisherType": publisher_type,
        "publishedAt": now,
        "objectCount": object_count,
        "deploymentReference": deployment_reference,
        "artifactManifestHash": artifact_manifest_hash,
        "result": "published",
    }
    return _write(receipts_dir, ledger, receipt)


def revoke_receipt(
    *,
    receipts_dir: Path,
    ledger,
    release_id: str,
    actor: str,
    reason: Optional[str],
    requested_objects: int,
    removed_objects: int,
    unavailable_objects: int,
    clock=None,
) -> dict:
    now = clock.iso() if clock is not None else utc_now_iso()
    receipt = {
        "receiptId": new_receipt_id(),
        "type": "revoke",
        "releaseId": release_id,
        "createdAt": now,
        "actor": actor,
        "reason": reason,
        "revokedAt": now,
        "requestedObjects": requested_objects,
        "removedObjects": removed_objects,
        "unavailableObjects": unavailable_objects,
        "cacheLimitations": "revoke does not invalidate previously downloaded copies",
    }
    return _write(receipts_dir, ledger, receipt)


def purge_receipt(
    *,
    receipts_dir: Path,
    ledger,
    release_id: str,
    actor: str,
    removed_objects: int,
    missing_objects: int,
    clock=None,
) -> dict:
    now = clock.iso() if clock is not None else utc_now_iso()
    receipt = {
        "receiptId": new_receipt_id(),
        "type": "purge",
        "releaseId": release_id,
        "createdAt": now,
        "actor": actor,
        "purgedAt": now,
        "removedObjects": removed_objects,
        "missingObjects": missing_objects,
        "retainedAuditRecords": True,
        "externalLimitations": "external caches are not guaranteed to be cleared",
    }
    return _write(receipts_dir, ledger, receipt)
