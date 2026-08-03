"""C4 end-to-end release lifecycle and failure-injection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from portal.canonical import read_json, write_json
from portal.errors import (
    BundleTamperedError,
    IdentityDriftError,
    NotApprovedError,
    OperationalError,
    SnapshotVerificationError,
    StateTransitionError,
)
from portal import lifecycle
from portal.tests.helpers import (
    approve_release,
    plan_dir,
    prepare_release,
    publish_release,
)


class TestFullLifecycle:
    def test_prepare_approve_publish_verify_status(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]

        approved = approve_release(portal_fixture, rid)
        assert approved["status"] == "approved"
        assert approved["releaseHash"] == prepared["releaseHash"]

        published = publish_release(portal_fixture, rid)
        assert published["status"] == "published"
        assert published["receipt"]["type"] == "publish"
        assert published["receipt"]["objectCount"] == 2

        st = lifecycle.status(portal_fixture.ledger, rid)
        assert st["status"] == "published"
        events = [e["event"] for e in st["events"]]
        assert "prepared" in events
        assert "approved" in events
        assert "published" in events

    def test_revoke_then_purge(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        publish_release(portal_fixture, rid)

        revoked = lifecycle.revoke(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
            actor="user.ops",
            reason="incorrect data",
            confirm_revoke=True,
        )
        assert revoked["status"] == "revoked"
        assert revoked["receipt"]["removedObjects"] == 2

        purged = lifecycle.purge(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
            actor="user.ops",
            confirm_purge=True,
        )
        assert purged["status"] == "purged"
        # Revoke already removed the deployed objects; purge accounts for them
        # as missing under publisher control (honest bookkeeping, no caches).
        assert purged["receipt"]["removedObjects"] == 0
        assert purged["receipt"]["missingObjects"] == 2
        assert purged["receipt"]["retainedAuditRecords"] is True

    def test_publish_without_approval_blocked(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        # The release is still in prepared state; publishing must fail closed
        # before any byte is deployed.
        with pytest.raises((NotApprovedError, StateTransitionError)):
            publish_release(portal_fixture, rid)

    def test_publish_without_confirmation_blocked(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        with pytest.raises(OperationalError):
            publish_release(portal_fixture, rid, confirm=False)

    def test_revoke_requires_published(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        with pytest.raises(StateTransitionError):
            lifecycle.revoke(
                release_id=rid,
                plan_dir=plan_dir(portal_fixture, rid),
                ledger=portal_fixture.ledger,
                receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
                deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
                actor="user.ops",
                reason=None,
                confirm_revoke=True,
            )

    def test_publish_idempotent_for_same_release_hash(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        first = publish_release(portal_fixture, rid)
        second = publish_release(portal_fixture, rid)
        assert first["status"] == "published"
        assert second["status"] == "published"
        assert first["receiptId"] == second["receiptId"]


class TestFailureInjection:
    def test_plan_tampered_after_approval_blocks_publish(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        p = plan_dir(portal_fixture, rid)
        plan = read_json(p / "plan.json")
        plan["objects"][0]["artifactHash"] = "0" * 64
        write_json(p / "plan.json", plan)
        with pytest.raises(BundleTamperedError):
            publish_release(portal_fixture, rid)

    def test_snapshot_tampered_after_approval_blocks_publish(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        subjects = portal_fixture.snapshot_dir / "canonical" / "subjects.json"
        (portal_fixture.snapshot_dir / "canonical").chmod(0o700)
        subjects.chmod(0o600)
        write_json(subjects, {"subjects": []})
        with pytest.raises(SnapshotVerificationError):
            publish_release(portal_fixture, rid)

    def test_identity_drift_blocks_publish(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        # Change the display name after approval => identity projection drift.
        identity_store = portal_fixture.identity_store
        for record in identity_store.records.values():
            record.display_name = "Drifted Name After Approval"
        identity_store._save()
        with pytest.raises(IdentityDriftError):
            publish_release(portal_fixture, rid)

    def test_release_hash_mismatch_with_ledger_blocks_publish(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        p = plan_dir(portal_fixture, rid)
        plan = read_json(p / "plan.json")
        plan["releaseHash"] = "f" * 64
        write_json(p / "plan.json", plan)
        with pytest.raises(BundleTamperedError):
            publish_release(portal_fixture, rid)


class TestAuthenticatedMode:
    def test_authenticated_prepare_approve_publish(self, auth_fixture):
        prepared = prepare_release(auth_fixture)
        rid = prepared["releaseId"]
        approved = approve_release(auth_fixture, rid)
        assert approved["status"] == "approved"
        published = publish_release(auth_fixture, rid)
        assert published["status"] == "published"
        cap = read_json(plan_dir(auth_fixture, rid) / "capability-manifest.json")
        for entry in cap["entries"]:
            assert entry["subjectRef"]
            assert entry["capabilityUrl"] is None
