"""C4 durable ledger state machine tests."""

from __future__ import annotations

import sqlite3

import pytest

from portal.errors import IdempotencyConflictError, LedgerError, StateTransitionError
from portal.ledger import (
    APPROVED,
    BLOCKED,
    PARTIAL,
    PREPARED,
    PUBLISHED,
    PUBLISHING,
    PURGED,
    REVOKED,
    PortalLedger,
)


@pytest.fixture
def ledger(tmp_path):
    db = PortalLedger(tmp_path / "portal-ledger.sqlite3")
    db.init()
    yield db
    db.close()


def _record(ledger, release_id="prelease_" + "a" * 24):
    ledger.record_release(
        release_id=release_id,
        release_hash="1" * 64,
        release_intent_hash="2" * 64,
        section_id="SEC-C4",
        publication_id="pub_c4",
        snapshot_mode="legacy-effective",
        portal_mode="static-encrypted",
        portal_app_version="1.0.0",
        hosting_profile_id="local-static-v1",
        object_count=2,
    )


class TestReleases:
    def test_record_and_read(self, ledger):
        _record(ledger)
        release = ledger.get_release("prelease_" + "a" * 24)
        assert release["status"] == PREPARED
        assert release["objectCount"] == 2

    def test_duplicate_release_rejected(self, ledger):
        _record(ledger)
        with pytest.raises(LedgerError):
            _record(ledger)


class TestTransitions:
    def test_prepare_to_approve_to_publish_to_revoke_to_purge(self, ledger):
        rid = "prelease_" + "b" * 24
        _record(ledger, rid)
        assert ledger.current_status(rid) == PREPARED

        ledger.transition(rid, PREPARED, APPROVED, "approved", "user.a")
        assert ledger.current_status(rid) == APPROVED

        run = ledger.begin_publish(rid, "idem-key", "local-static-v1", "local-static")
        assert ledger.current_status(rid) == PUBLISHING

        ledger.complete_publish(
            run, rid,
            [{"objectId": "o" * 32, "projectionHash": "5" * 64, "artifactHash": "7" * 64}],
            "rcpt_x",
        )
        assert ledger.current_status(rid) == PUBLISHED

        ledger.transition(rid, PUBLISHED, REVOKED, "revoked", "user.r")
        assert ledger.current_status(rid) == REVOKED

        ledger.transition(rid, REVOKED, PURGED, "purged", "user.p")
        assert ledger.current_status(rid) == PURGED

    def test_illegal_transition(self, ledger):
        rid = "prelease_" + "c" * 24
        _record(ledger, rid)
        with pytest.raises(StateTransitionError):
            ledger.transition(rid, PREPARED, PUBLISHED, "skip", "user.x")

    def test_revoked_cannot_republish(self, ledger):
        rid = "prelease_" + "d" * 24
        _record(ledger, rid)
        ledger.transition(rid, PREPARED, APPROVED, "approved", "user.a")
        run = ledger.begin_publish(rid, "idem-key2", "local-static-v1", "local-static")
        ledger.complete_publish(
            run, rid,
            [{"objectId": "o" * 32, "projectionHash": "5" * 64, "artifactHash": "7" * 64}],
            "rcpt_y",
        )
        ledger.transition(rid, PUBLISHED, REVOKED, "revoked", "user.r")
        with pytest.raises(StateTransitionError):
            ledger.begin_publish(rid, "idem-key3", "local-static-v1", "local-static")

    def test_publish_only_from_approved(self, ledger):
        rid = "prelease_" + "e" * 24
        _record(ledger, rid)
        with pytest.raises(StateTransitionError):
            ledger.begin_publish(rid, "idem-key4", "local-static-v1", "local-static")


class TestIdempotency:
    def test_unique_idempotency_key(self, ledger):
        rid = "prelease_" + "f" * 24
        _record(ledger, rid)
        ledger.transition(rid, PREPARED, APPROVED, "approved", "user.a")
        ledger.begin_publish(rid, "shared-key", "local-static-v1", "local-static")
        with pytest.raises(IdempotencyConflictError):
            ledger.begin_publish(rid, "shared-key", "local-static-v1", "local-static")

    def test_publish_fail_moves_to_partial(self, ledger):
        rid = "prelease_" + "g" * 24
        _record(ledger, rid)
        ledger.transition(rid, PREPARED, APPROVED, "approved", "user.a")
        run = ledger.begin_publish(rid, "idem-key5", "local-static-v1", "local-static")
        ledger.fail_publish(run, rid)
        assert ledger.current_status(rid) == PARTIAL


class TestIntegrity:
    def test_integrity_check_ok(self, ledger):
        _record(ledger)
        assert ledger.integrity_check() == ["ok"]

    def test_foreign_key_check_ok(self, ledger):
        _record(ledger)
        assert ledger.foreign_key_check() == []

    def test_receipt_persisted(self, ledger):
        _record(ledger)
        receipt = {
            "receiptId": "rcpt_1",
            "type": "publish",
            "releaseId": "prelease_" + "a" * 24,
            "createdAt": "2026-01-01T00:00:00Z",
        }
        ledger.record_receipt(receipt)
        assert ledger.get_receipt("rcpt_1") == receipt

    def test_hosting_profile_registered(self, ledger):
        from portal.models import HostingProfile

        profile = HostingProfile(
            profile_id="p", mode="static-encrypted", base_url="https://h/",
            tls_required=True, directory_listing_disabled=True,
            header_policy={}, cache_policy={"mode": "no-store"},
            supports_atomic_promotion=True, supports_delete=True, supports_purge=True,
        )
        ledger.register_hosting_profile(profile)
        conn = ledger._connect()
        try:
            row = conn.execute("SELECT profileId, profileHash FROM hosting_profiles").fetchone()
        finally:
            conn.close()
        assert row["profileId"] == "p"
        assert row["profileHash"] == profile.profile_hash
