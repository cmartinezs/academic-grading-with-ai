"""C4 hosting publisher tests: local static deploy/revoke/purge and
authenticated subject isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from portal.canonical import read_json
from portal.errors import PreflightError, PublisherUnavailableError
from portal.publisher import get_publisher, publisher_for_mode
from portal.tests.helpers import (
    approve_release,
    plan_dir,
    prepare_release,
    publish_release,
)


class TestRegistry:
    def test_known_publisher_types(self):
        assert get_publisher("local-static").publisher_type == "local-static"
        assert get_publisher("fake-authenticated").publisher_type == "fake-authenticated"

    def test_unknown_publisher_fails_closed(self):
        with pytest.raises(PublisherUnavailableError):
            get_publisher("firebase-prod")

    def test_publisher_for_mode(self):
        assert publisher_for_mode("static-encrypted").publisher_type == "local-static"
        assert publisher_for_mode("authenticated").publisher_type == "fake-authenticated"


class TestLocalStaticDeploy:
    def test_publish_creates_deployment(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        published = publish_release(portal_fixture, rid)
        deployment = Path(published["receipt"]["deploymentReference"])
        assert deployment.exists()
        public_manifest = read_json(plan_dir(portal_fixture, rid) / "public-bundle" / "manifest.json")
        for entry in public_manifest["objects"]:
            obj_dir = deployment / entry["objectId"]
            assert (obj_dir / "index.html").exists()
            assert (obj_dir / "app.js").exists()
            assert (obj_dir / "styles.css").exists()
            assert (obj_dir / "payload.enc").exists()
            assert (obj_dir / "metadata.json").exists()

    def test_revoke_removes_deployment_objects(self, portal_fixture):
        from portal import lifecycle

        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        published = publish_release(portal_fixture, rid)
        deployment = Path(published["receipt"]["deploymentReference"])
        lifecycle.revoke(
            release_id=rid,
            plan_dir=plan_dir(portal_fixture, rid),
            ledger=portal_fixture.ledger,
            receipts_dir=portal_fixture.roots / "state" / "portal" / "receipts",
            deployments_root=portal_fixture.roots / "state" / "portal" / "deployments",
            actor="user.ops",
            reason="test",
            confirm_revoke=True,
        )
        assert not any(deployment.glob("*/index.html"))

    def test_static_preflight_rejects_wrong_mode(self, portal_fixture, auth_fixture):
        from portal.lifecycle import _plan_doc

        publisher = get_publisher("local-static")
        # An authenticated plan cannot be served by the static publisher.
        auth = prepare_release(auth_fixture)
        plan = _plan_doc(plan_dir(auth_fixture, auth["releaseId"]))
        profile = publisher._profile_from_plan(plan)
        with pytest.raises(PreflightError):
            publisher.preflight(profile, plan_dir(auth_fixture, auth["releaseId"]), auth_fixture.ledger)


class TestAuthenticatedIsolation:
    def test_subject_bound_access(self, auth_fixture):
        from portal.hosting.fake_authenticated import FakeAuthenticatedPublisher

        adapter = FakeAuthenticatedPublisher()
        assert adapter.verify_subject_access("ref-a", "ref-a", auth_fixture.hosting_profile)
        assert not adapter.verify_subject_access("ref-a", "ref-b", auth_fixture.hosting_profile)
        assert not adapter.verify_subject_access("", "ref-a", auth_fixture.hosting_profile)
        assert not adapter.verify_subject_access(None, None, auth_fixture.hosting_profile)

    def test_publish_stores_per_subject_projections(self, auth_fixture):
        prepared = prepare_release(auth_fixture)
        rid = prepared["releaseId"]
        approve_release(auth_fixture, rid)
        published = publish_release(auth_fixture, rid)
        store = Path(published["receipt"]["deploymentReference"])
        cap = read_json(plan_dir(auth_fixture, rid) / "capability-manifest.json")
        refs = [entry["subjectRef"] for entry in cap["entries"]]
        assert len(set(refs)) == 2
        for ref in refs:
            assert (store / f"{ref}.json").exists()

    def test_subject_a_cannot_read_b(self, auth_fixture):
        prepared = prepare_release(auth_fixture)
        rid = prepared["releaseId"]
        approve_release(auth_fixture, rid)
        published = publish_release(auth_fixture, rid)
        store = Path(published["receipt"]["deploymentReference"])
        cap = read_json(plan_dir(auth_fixture, rid) / "capability-manifest.json")
        refs = [entry["subjectRef"] for entry in cap["entries"]]
        from portal.hosting.fake_authenticated import FakeAuthenticatedPublisher

        adapter = FakeAuthenticatedPublisher()
        # A authenticating with its own reference cannot address B's projection.
        assert not adapter.verify_subject_access(refs[0], refs[1], auth_fixture.hosting_profile)
        # And there is no global listing endpoint on the adapter.
        assert not hasattr(adapter, "list_subjects")
