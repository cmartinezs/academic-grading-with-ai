"""C4 source-snapshot verification.

C4 never trusts a publication manifest by inspection. The canonical C1 verifier
(`publication.verify.verify_snapshot`) is the authority for contract, semantic,
privacy, manifest, classification, lifecycle, and immutability gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .canonical import read_json
from .errors import (
    SnapshotModeError,
    SnapshotNotApprovedError,
    SnapshotTerminalError,
    SnapshotVerificationError,
)

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})
SNAPSHOT_REQUIRED_STATE = frozenset({"approved"})

SNAPSHOT_MODES = ("legacy-effective", "grade-policy-effective")


@dataclass(frozen=True)
class VerifiedSnapshot:
    content_hash: str
    review_hash: str
    section_id: str
    publication_id: str
    snapshot_mode: str
    lifecycle_state: str


def derive_snapshot_mode(snapshot_dir: Path) -> str:
    policy_path = Path(snapshot_dir) / "canonical" / "policy.json"
    if not policy_path.exists():
        raise SnapshotModeError(
            "canonical/policy.json missing from snapshot — cannot derive snapshotMode."
        )
    policy = read_json(policy_path)
    mode = policy.get("mode")
    if mode not in SNAPSHOT_MODES:
        raise SnapshotModeError(
            f"Invalid snapshot mode in canonical/policy.json: {mode!r}"
        )
    return str(mode)


def verify_snapshot_state(lifecycle_ledger, publication_id: str) -> str:
    if lifecycle_ledger is None:
        raise SnapshotTerminalError(
            "lifecycle_ledger is required for snapshot verification — fail closed."
        )
    state = lifecycle_ledger.current_state(publication_id)
    if state in SNAPSHOT_TERMINAL_STATES:
        raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
    if state not in SNAPSHOT_REQUIRED_STATE:
        raise SnapshotNotApprovedError(
            f"Snapshot state is {state}, expected approved."
        )
    return state


def verify_source_snapshot(
    snapshot_dir: Path,
    section_id: str,
    publication_id: str,
    lifecycle_ledger=None,
) -> VerifiedSnapshot:
    """Verify an approved immutable C1/C2 snapshot and its lifecycle state."""
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
        raise SnapshotVerificationError(
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
        raise SnapshotVerificationError(
            "Verified snapshot is missing immutable content/review hashes."
        )

    snapshot_mode = derive_snapshot_mode(snapshot_dir)
    lifecycle_state = verify_snapshot_state(lifecycle_ledger, publication_id)

    return VerifiedSnapshot(
        content_hash=content_hash,
        review_hash=review_hash,
        section_id=str(manifest.get("sectionId")),
        publication_id=str(manifest.get("publicationId")),
        snapshot_mode=snapshot_mode,
        lifecycle_state=lifecycle_state,
    )


def read_canonical(snapshot_dir: Path, rel: str) -> dict:
    path = Path(snapshot_dir) / rel
    if not path.exists():
        return {}
    return read_json(path)
