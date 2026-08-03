"""C4 privacy tests: no PII, keys, or plaintext in public artifacts or audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from portal.canonical import read_json
from portal.tests.helpers import approve_release, plan_dir, prepare_release, publish_release


def _public_bundle_text(plan_dir_path: Path) -> str:
    chunks = []
    for path in sorted((plan_dir_path / "public-bundle").rglob("*")):
        if path.is_file():
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(chunks)


def _all_receipt_texts(roots) -> str:
    chunks = []
    receipts_dir = roots / "state" / "portal" / "receipts"
    if receipts_dir.exists():
        for path in sorted(receipts_dir.glob("*.json")):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


class TestPublicBundlePrivacy:
    def test_no_pii_in_public_bundle(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        text = _public_bundle_text(plan_dir(portal_fixture, prepared["releaseId"]))
        assert "Ana" not in text
        assert "Bruno" not in text
        assert "11111111-1" not in text
        assert "22222222-2" not in text
        assert "example.test" not in text
        assert "70.0" not in text or "Buen trabajo" not in text

    def test_no_plaintext_payload_in_public_bundle(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        text = _public_bundle_text(plan_dir(portal_fixture, prepared["releaseId"]))
        assert '"score"' not in text
        assert '"finalOutcome"' not in text

    def test_no_capability_keys_in_public_bundle(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        cap = read_json(plan_dir(portal_fixture, prepared["releaseId"]) / "capability-manifest.json")
        text = _public_bundle_text(plan_dir(portal_fixture, prepared["releaseId"]))
        for entry in cap["entries"]:
            assert entry["key"] not in text

    def test_public_metadata_has_no_student_fields(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        p = plan_dir(portal_fixture, prepared["releaseId"])
        for metadata in (p / "public-bundle" / "objects").glob("*.metadata.json"):
            doc = read_json(metadata)
            assert "studentId" not in doc
            assert "displayName" not in doc
            assert "email" not in doc
            assert "key" not in doc
            assert "grade" not in doc


class TestReceiptPrivacy:
    def test_receipts_have_no_keys_or_pii(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        publish_release(portal_fixture, rid)
        text = _all_receipt_texts(portal_fixture.roots)
        cap = read_json(plan_dir(portal_fixture, rid) / "capability-manifest.json")
        for entry in cap["entries"]:
            assert entry["key"] not in text
            assert entry["capabilityUrl"] not in text
        assert "Ana" not in text
        assert "11111111-1" not in text


class TestLedgerPrivacy:
    def test_ledger_has_no_keys(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        publish_release(portal_fixture, rid)
        cap = read_json(plan_dir(portal_fixture, rid) / "capability-manifest.json")
        db_path = portal_fixture.roots / "state" / "portal" / "portal-ledger.sqlite3"
        raw = db_path.read_bytes()
        for entry in cap["entries"]:
            assert entry["key"].encode() not in raw

    def test_ledger_has_no_pii(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        rid = prepared["releaseId"]
        approve_release(portal_fixture, rid)
        publish_release(portal_fixture, rid)
        db_path = portal_fixture.roots / "state" / "portal" / "portal-ledger.sqlite3"
        raw = db_path.read_bytes()
        assert b"11111111-1" not in raw
        assert b"example.test" not in raw


class TestPermissions:
    def test_plan_dir_permissions(self, portal_fixture):
        prepared = prepare_release(portal_fixture)
        p = plan_dir(portal_fixture, prepared["releaseId"])
        mode = p.stat().st_mode & 0o777
        assert mode == 0o700
        cap = p / "capability-manifest.json"
        assert (cap.stat().st_mode & 0o777) == 0o600
