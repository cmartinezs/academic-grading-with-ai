"""C4 publisher contract and shared preflight gates.

All publishers fail closed: an invalid hosting profile, an unapproved or
terminal snapshot, a tampered bundle, an unavailable ledger, or a plan mismatch
blocks publish before any bytes are written. Publisher implementations never
receive capability keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..errors import PreflightError, PublisherError
from ..models import HostingProfile


@dataclass(frozen=True)
class PublishResult:
    deployment_reference: str
    artifact_manifest_hash: str
    object_count: int


@dataclass(frozen=True)
class RevokeResult:
    removed_objects: int
    unavailable_objects: int


@dataclass(frozen=True)
class PurgeResult:
    removed_objects: int
    missing_objects: int


def preflight_profile(profile: HostingProfile) -> None:
    """Fail closed unless the hosting profile satisfies its mode requirements."""
    if not isinstance(profile, HostingProfile):
        raise PreflightError("A validated HostingProfile is required.")
    try:
        profile.validate_mode_requirements()
    except Exception as exc:
        raise PreflightError(f"Hosting profile preflight failed: {exc}") from exc


def preflight_snapshot(snapshot_dir: Path, section_id: str, publication_id: str, lifecycle_ledger) -> None:
    from ..snapshot import verify_source_snapshot

    try:
        verify_source_snapshot(snapshot_dir, section_id, publication_id, lifecycle_ledger)
    except Exception as exc:
        raise PreflightError(f"Snapshot preflight failed: {exc}") from exc


def preflight_bundle(plan_dir: Path) -> dict:
    from ..approval import _verify_bundle

    return _verify_bundle(plan_dir)


def preflight_ledger(ledger) -> None:
    if ledger is None:
        raise PreflightError("Ledger is unavailable; refusing to publish.")
    try:
        integrity = ledger.integrity_check()
    except Exception as exc:
        raise PreflightError(f"Ledger integrity check failed: {exc}") from exc
    if integrity != ["ok"]:
        raise PreflightError(f"Ledger integrity check failed: {integrity}")


class AbstractPublisher(ABC):
    """Base contract for portal publishers."""

    publisher_type: str = "abstract"

    @abstractmethod
    def preflight(self, profile: HostingProfile, plan_dir: Path, ledger) -> None:
        """Fail closed when the deployment target cannot satisfy the profile."""

    @abstractmethod
    def publish(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
                deployments_root: Path) -> PublishResult:
        """Deploy the approved public bundle. Returns durable results."""

    @abstractmethod
    def revoke(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
               deployments_root: Path, actor: str, reason: Optional[str]) -> RevokeResult:
        """Remove access to a published release (best effort, durable receipt)."""

    @abstractmethod
    def purge(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
              deployments_root: Path, actor: str) -> PurgeResult:
        """Delete objects under publisher control (best effort, durable receipt)."""
