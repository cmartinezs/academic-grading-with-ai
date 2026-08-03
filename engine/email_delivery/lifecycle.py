"""Lifecycle and source-snapshot gates for C3 email delivery.

C3 never trusts a publication manifest by inspection alone.  The canonical C1
verifier is the authority for contract, semantic, privacy, manifest,
classification, lifecycle, and immutability gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .canonical import compute_identity_projection_hash, read_json
from .errors import (
    IdentityDriftError,
    PlanTamperedError,
    SnapshotNotApprovedError,
    SnapshotTerminalError,
)
from .recipients import normalize_email

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})
SNAPSHOT_SENDABLE_STATES = frozenset({"approved"})


def check_snapshot_sendable(lifecycle_ledger, publication_id: str) -> str:
    if lifecycle_ledger is None:
        raise SnapshotTerminalError(
            "lifecycle_ledger is required for snapshot verification — fail closed"
        )
    state = lifecycle_ledger.current_state(publication_id)
    if state in SNAPSHOT_TERMINAL_STATES:
        raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
    if state not in SNAPSHOT_SENDABLE_STATES:
        raise SnapshotNotApprovedError(
            f"Snapshot state is {state}, expected approved."
        )
    return state


def check_identity_drift(plan_dict: dict, identity_store) -> list[str]:
    drifts: list[str] = []
    for recipient in plan_dict.get("recipients", []):
        student_id = recipient.get("studentId")
        stored_hash = recipient.get("identityProjectionHash")
        identity = identity_store.resolve(student_id)
        if identity is None:
            drifts.append(f"studentId {student_id} no longer in IdentityStore")
            continue
        email = (identity.contact or {}).get("email", "")
        display_name = identity.display_name or ""
        try:
            normalized = normalize_email(email)
        except Exception:
            drifts.append(f"Identity contact invalid for {student_id}")
            continue
        current_hash = compute_identity_projection_hash(
            student_id, display_name, normalized
        )
        if current_hash != stored_hash:
            drifts.append(f"Identity drift for {student_id}")
    return drifts


def check_plan_integrity(plan_dir: Path, plan_id: str, preview_hash: str) -> bool:
    plan_path = plan_dir / "plan.json"
    if not plan_path.exists():
        return False
    plan_dict = read_json(plan_path)
    return (
        plan_dict.get("planId") == plan_id
        and plan_dict.get("previewHash") == preview_hash
    )


def derive_snapshot_mode(snapshot_dir: Path) -> str:
    policy_path = snapshot_dir / "canonical" / "policy.json"
    if not policy_path.exists():
        raise SnapshotTerminalError(
            "canonical/policy.json missing from snapshot — cannot derive snapshotMode"
        )
    policy = read_json(policy_path)
    mode = policy.get("mode")
    if mode not in ("legacy-effective", "grade-policy-effective"):
        raise SnapshotTerminalError(
            f"Invalid snapshot mode in canonical/policy.json: {mode!r}"
        )
    return str(mode)


@dataclass(frozen=True)
class VerifiedSnapshot:
    content_hash: str
    review_hash: str
    section_id: str
    publication_id: str
    snapshot_mode: str
    lifecycle_state: str


def verify_email_source_snapshot(
    snapshot_dir: Path,
    section_id: str,
    publication_id: str,
    lifecycle_ledger=None,
) -> VerifiedSnapshot:
    """Verify an approved immutable C1 snapshot and its operational lifecycle."""
    from publication.verify import verify_snapshot

    snapshot_dir = Path(snapshot_dir)
    report = verify_snapshot(
        snapshot_dir,
        section_id=section_id,
        publication_id=publication_id,
        immutable=True,
    )
    if not report.passed():
        gates = sorted({finding.gate for finding in report.findings})
        gate_summary = ",".join(gates) if gates else "unknown"
        raise PlanTamperedError(
            "Snapshot verification failed "
            f"({len(report.findings)} finding(s); gates={gate_summary})."
        )

    manifest = read_json(snapshot_dir / "manifest.json")
    if manifest.get("status") != "approved":
        raise SnapshotNotApprovedError(
            f"Snapshot manifest status is {manifest.get('status')!r}, expected approved."
        )

    content_hash = manifest.get("contentHash")
    review_hash = manifest.get("reviewHash")
    if not isinstance(content_hash, str) or not isinstance(review_hash, str):
        raise PlanTamperedError("Verified snapshot is missing immutable hashes.")

    snapshot_mode = derive_snapshot_mode(snapshot_dir)
    lifecycle_state = check_snapshot_sendable(lifecycle_ledger, publication_id)

    return VerifiedSnapshot(
        content_hash=content_hash,
        review_hash=review_hash,
        section_id=str(manifest.get("sectionId")),
        publication_id=str(manifest.get("publicationId")),
        snapshot_mode=snapshot_mode,
        lifecycle_state=lifecycle_state,
    )
