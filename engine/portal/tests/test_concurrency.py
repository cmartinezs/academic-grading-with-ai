"""C4 concurrency tests: two agents racing on prepare/publish/revoke must
produce one winner and one clean idempotent no-op (no double writes)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from portal import lifecycle
from portal.errors import IdentityDriftError, OperationalError, StateTransitionError
from portal.tests.helpers import (
    _Roots,
    approve_release,
    plan_dir,
    prepare_release,
    publish_release,
)
from portal.canonical import read_json


class TestPrepareRace:
    def test_two_prepares_yield_same_plan(self, portal_fixture):
        def worker(_):
            return prepare_release(portal_fixture)

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(worker, [1, 2]))
        plan_ids = {r["releaseId"] for r in results}
        hashes = {r["releaseHash"] for r in results}
        assert len(plan_ids) == 1
        assert len(hashes) == 1
        plan = read_json(plan_dir(portal_fixture, results[0]["releaseId"]) / "plan.json")
        assert plan["releaseHash"] == results[0]["releaseHash"]


class TestPublishRace:
    def test_double_publish_is_idempotent(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)

        def worker(_):
            return publish_release(portal_fixture, rid)

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(worker, [1, 2]))
        receipts = [r["receipt"]["receiptId"] for r in results]
        assert len(set(receipts)) == 1
        assert results[0]["status"] == "published"
        assert results[1]["status"] == "published"
        runs = portal_fixture.ledger.list_publish_runs(rid)
        assert len(runs) == 1

    def test_concurrent_prepare_and_publish_dont_interleave(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)

        def publish_worker(_):
            return publish_release(portal_fixture, rid)

        def revoke_worker(_):
            from portal.errors import OperationalError

            try:
                return lifecycle.revoke(
                    release_id=rid,
                    plan_dir=plan_dir(portal_fixture, rid),
                    ledger=portal_fixture.ledger,
                    receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
                    deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
                    actor="user.ops",
                    reason="race",
                    confirm_revoke=True,
                )
            except (StateTransitionError, OperationalError):
                return "skipped"

        with ThreadPoolExecutor(max_workers=2) as ex:
            pub_future = ex.submit(publish_worker, 1)
            rev_future = ex.submit(revoke_worker, 2)
            pub_result = pub_future.result()
            rev_result = rev_future.result()
        assert pub_result["status"] in ("published", "blocked")
        # A revoke that raced ahead leaves a clean terminal state.
        if isinstance(rev_result, dict) and rev_result.get("status") == "revoked":
            assert pub_result["status"] == "blocked"
