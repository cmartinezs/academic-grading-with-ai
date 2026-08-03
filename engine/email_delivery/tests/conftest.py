"""Shared C3 test fixtures.

The historical monolithic unit suite intentionally uses lightweight synthetic
snapshot dictionaries.  Those tests isolate C3 behavior and therefore stub the
C1 snapshot boundary.  Dedicated integration tests in
``test_snapshot_authority.py`` exercise the real C1 verifier end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_legacy_unit_suite(request, monkeypatch):
    if request.node.path.name != "test_email_delivery.py":
        return

    from email_delivery import approval as approval_module
    from email_delivery import executor as executor_module
    from email_delivery import lifecycle as lifecycle_module
    from email_delivery.canonical import read_json

    def fake_verify_snapshot(snapshot_dir, section_id, publication_id, lifecycle_ledger=None):
        snapshot_dir = Path(snapshot_dir)
        manifest = {}
        plan = {}
        policy = {}
        if (snapshot_dir / "manifest.json").is_file():
            manifest = read_json(snapshot_dir / "manifest.json")
        if (snapshot_dir / "plan.json").is_file():
            plan = read_json(snapshot_dir / "plan.json")
        if (snapshot_dir / "canonical" / "policy.json").is_file():
            policy = read_json(snapshot_dir / "canonical" / "policy.json")

        state = "approved"
        if lifecycle_ledger is not None:
            state = lifecycle_ledger.current_state(publication_id)

        return lifecycle_module.VerifiedSnapshot(
            content_hash=(
                manifest.get("contentHash")
                or plan.get("snapshotContentHash")
                or "a" * 64
            ),
            review_hash=(
                manifest.get("reviewHash")
                or plan.get("snapshotReviewHash")
                or "b" * 64
            ),
            section_id=plan.get("sectionId") or section_id,
            publication_id=plan.get("publicationId") or publication_id,
            snapshot_mode=(
                policy.get("mode")
                or plan.get("snapshotMode")
                or "legacy-effective"
            ),
            lifecycle_state=state,
        )

    monkeypatch.setattr(
        lifecycle_module,
        "verify_email_source_snapshot",
        fake_verify_snapshot,
    )

    original_approve = approval_module.approve_plan
    original_execute = executor_module.execute_plan

    def approve_with_snapshot(*args, **kwargs):
        kwargs.setdefault("snapshot_dir", kwargs.get("plan_dir"))
        return original_approve(*args, **kwargs)

    def execute_with_snapshot(*args, **kwargs):
        kwargs.setdefault("snapshot_dir", kwargs.get("plan_dir"))
        return original_execute(*args, **kwargs)

    # The historical suite imported these callables directly at module import.
    monkeypatch.setattr(request.module, "approve_plan", approve_with_snapshot)
    monkeypatch.setattr(request.module, "execute_plan", execute_with_snapshot)
