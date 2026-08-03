"""Shared helpers for C4 portal tests."""

from __future__ import annotations

from pathlib import Path

from portal import lifecycle


class _Roots:
    """Test-only runtime roots mirroring c0.paths.resolve_runtime_roots."""

    def __init__(self, root: Path):
        root = Path(root)
        self.private_root = root / "priv"
        self.state_root = root / "state"
        self.publications_root = root / "pub"
        self.temp_root = root / "tmp"


def prepare_release(fixture, portal_mode=None):
    return lifecycle.prepare(
        roots=_Roots(fixture.roots),
        section_id=fixture.section_id,
        publication_id=fixture.publication_id,
        snapshot_dir=fixture.snapshot_dir,
        hosting_profile=fixture.hosting_profile,
        portal_mode=portal_mode or fixture.portal_mode,
        identity_store=fixture.identity_store,
        lifecycle_ledger=fixture.lifecycle_ledger,
        ledger=fixture.ledger,
    )


def plan_dir(fixture, release_id):
    return (
        Path(fixture.roots)
        / "priv"
        / "portal"
        / "plans"
        / fixture.section_id
        / fixture.publication_id
        / release_id
    )


def approve_release(fixture, release_id, actor="user.approver1"):
    return lifecycle.approve(
        release_id=release_id,
        plan_dir=plan_dir(fixture, release_id),
        actor=actor,
        ledger=fixture.ledger,
        identity_store=fixture.identity_store,
        lifecycle_ledger=fixture.lifecycle_ledger,
        publication_id=fixture.publication_id,
        snapshot_dir=fixture.snapshot_dir,
        confirm_reviewed=True,
    )


def publish_release(fixture, release_id, publisher_type=None, confirm=True):
    return lifecycle.publish(
        release_id=release_id,
        plan_dir=plan_dir(fixture, release_id),
        publisher_type=publisher_type
        or ("fake-authenticated" if fixture.portal_mode == "authenticated" else "local-static"),
        ledger=fixture.ledger,
        receipts_dir=Path(fixture.roots) / "state" / "portal" / "receipts",
        deployments_root=Path(fixture.roots) / "state" / "portal" / "deployments",
        identity_store=fixture.identity_store,
        lifecycle_ledger=fixture.lifecycle_ledger,
        publication_id=fixture.publication_id,
        snapshot_dir=fixture.snapshot_dir,
        confirm_publish=confirm,
    )
