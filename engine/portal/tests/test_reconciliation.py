"""C4 reconciliation tests: partial publish recovery and deployment drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from portal import lifecycle, reconciliation
from portal.canonical import read_json
from portal.tests.helpers import (
    _Roots,
    approve_release,
    plan_dir,
    prepare_release,
    publish_release,
)


class TestReconcilePartial:
    def _simulate_partial(self, portal_fixture, rid):
        ledger = portal_fixture.ledger
        run_id = ledger.begin_publish(
            rid,
            idempotency_key=f"key-{rid}",
            hosting_profile_id=portal_fixture.hosting_profile.profile_id,
            publisher_type="local-static",
        )
        ledger.fail_publish(run_id, rid, now="2026-08-03T00:00:00Z")
        assert portal_fixture.ledger.get_release(rid)["status"] == "partial"

    def test_partial_publish_recovers_to_published(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        # Simulate a crash after the physical deploy but before the ledger run
        # completed: objects are on disk, the run is recorded as partial.
        from portal.hosting.local_static import LocalStaticPublisher
        from portal.lifecycle import _plan_doc

        publisher = LocalStaticPublisher()
        plan_doc = _plan_doc(plan_dir(portal_fixture, rid))
        result = publisher.publish(
            plan_dir=plan_dir(portal_fixture, rid),
            plan_doc=plan_doc,
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
        )
        assert result.object_count == 2
        self._simulate_partial(portal_fixture, rid)

        result = reconciliation.reconcile_release(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
            actor="user.ops",
        )
        assert result["status"] == "published"
        assert result["receipt"]["objectCount"] == 2
        assert portal_fixture.ledger.get_release(rid)["status"] == "published"

    def test_partial_publish_marks_blocked_when_unrecoverable(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        # Simulate a crash before anything reached the publisher: nothing is on
        # disk, the run is partial, so reconciliation cannot complete it.
        self._simulate_partial(portal_fixture, rid)

        result = reconciliation.reconcile_release(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
            actor="user.ops",
        )
        assert result["status"] == "blocked"
        assert portal_fixture.ledger.get_release(rid)["status"] == "blocked"


class TestDeploymentDrift:
    def test_missing_deployment_object_reported(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        published = publish_release(portal_fixture, rid)
        deployment = Path(published["receipt"]["deploymentReference"])
        # Delete one deployed object directory => drift.
        victim = next(deployment.glob("*/index.html")).parent
        import shutil

        shutil.rmtree(victim)
        report = reconciliation.diff_deployment(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
        )
        assert report["missingObjects"] == 1

    def test_clean_deployment_has_no_drift(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        publish_release(portal_fixture, rid)
        report = reconciliation.diff_deployment(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
        )
        assert report["missingObjects"] == 0
        assert report["deploymentComplete"] is True
