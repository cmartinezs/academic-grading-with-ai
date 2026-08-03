"""C4 release bundle preparation integration tests (real approved snapshot)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from portal.bundle import _recompute_and_compare
from portal.canonical import read_json, write_json
from portal.errors import BundleError, BundleTamperedError
from portal import lifecycle
from portal.tests.helpers import prepare_release, plan_dir

from c0.identity import IdentityStore


def _opaque_id(fixture, rut):
    return fixture.identity_store.resolve_by_external("rut", rut)


class TestPrepare:
    def test_prepare_creates_release(self, portal_fixture):
        result = prepare_release(portal_fixture)
        assert result["releaseId"].startswith("prelease_")
        assert len(result["releaseHash"]) == 64
        assert result["objectCount"] == 2
        plan_dir_path = plan_dir(portal_fixture, result["releaseId"])
        assert (plan_dir_path / "plan.json").exists()
        assert (plan_dir_path / "capability-manifest.json").exists()
        assert (plan_dir_path / "public-bundle" / "manifest.json").exists()

    def test_release_hash_is_deterministic_across_repare(self, portal_fixture):
        first = prepare_release(portal_fixture)
        second = prepare_release(portal_fixture)
        assert first["releaseId"] == second["releaseId"]
        assert first["releaseHash"] == second["releaseHash"]

    def test_release_hash_matches_recomputation(self, portal_fixture):
        result = prepare_release(portal_fixture)
        plan = read_json(plan_dir(portal_fixture, result["releaseId"]) / "plan.json")
        _recompute_and_compare(plan_dir(portal_fixture, result["releaseId"]), plan)

    def test_object_ids_unique_within_release(self, portal_fixture):
        result = prepare_release(portal_fixture)
        cap = read_json(plan_dir(portal_fixture, result["releaseId"]) / "capability-manifest.json")
        object_ids = [entry["objectId"] for entry in cap["entries"]]
        assert len(object_ids) == len(set(object_ids)) == 2

    def test_object_ids_not_derived_from_student(self, portal_fixture):
        result = prepare_release(portal_fixture)
        cap = read_json(plan_dir(portal_fixture, result["releaseId"]) / "capability-manifest.json")
        stu_a = _opaque_id(portal_fixture, "11111111-1")
        entry = next(e for e in cap["entries"] if e["studentId"] == stu_a)
        assert stu_a not in entry["objectId"]
        assert entry["objectId"][:4] != stu_a[:4]

    def test_keys_in_capability_manifest_not_in_plan(self, portal_fixture):
        result = prepare_release(portal_fixture)
        plan = read_json(plan_dir(portal_fixture, result["releaseId"]) / "plan.json")
        cap = read_json(plan_dir(portal_fixture, result["releaseId"]) / "capability-manifest.json")
        for entry in cap["entries"]:
            assert "key" in entry and entry["key"]
            assert entry["key"] not in json.dumps(plan)

    def test_capability_url_contains_key_in_fragment(self, portal_fixture):
        result = prepare_release(portal_fixture)
        cap = read_json(plan_dir(portal_fixture, result["releaseId"]) / "capability-manifest.json")
        for entry in cap["entries"]:
            assert entry["capabilityUrl"].startswith("https://portal.example.test/")
            assert "#k=" in entry["capabilityUrl"]

    def test_tampered_plan_detected(self, portal_fixture):
        result = prepare_release(portal_fixture)
        p = plan_dir(portal_fixture, result["releaseId"])
        plan = read_json(p / "plan.json")
        plan["objectCount"] = 999
        write_json(p / "plan.json", plan)
        with pytest.raises(BundleTamperedError):
            _recompute_and_compare(p, read_json(p / "plan.json"))

    def test_tampered_capability_manifest_detected(self, portal_fixture):
        result = prepare_release(portal_fixture)
        p = plan_dir(portal_fixture, result["releaseId"])
        cap = read_json(p / "capability-manifest.json")
        cap["entries"][0]["projectionHash"] = "0" * 64
        write_json(p / "capability-manifest.json", cap)
        plan = read_json(p / "plan.json")
        with pytest.raises(BundleTamperedError):
            _recompute_and_compare(p, plan)


class TestPrepareC2:
    def test_c2_release_prepares(self, c2_fixture):
        result = prepare_release(c2_fixture)
        plan = read_json(plan_dir(c2_fixture, result["releaseId"]) / "plan.json")
        assert plan["snapshot"]["mode"] == "grade-policy-effective"
        assert result["objectCount"] == 2


class TestPrepareFailClosed:
    def test_snapshot_terminal_blocks_prepare(self, portal_fixture):
        # Revoke the source snapshot lifecycle state, then re-prepare must fail.
        portal_fixture.lifecycle_ledger.append(
            "revoked", portal_fixture.publication_id, actor="user.revoker"
        )
        with pytest.raises(Exception) as exc_info:
            prepare_release(portal_fixture)
        from portal.errors import SnapshotTerminalError

        assert isinstance(exc_info.value, SnapshotTerminalError)

    def test_tampered_snapshot_detected_fail_closed(self, portal_fixture):
        # Approved snapshots are immutable: tampering canonical data must be
        # rejected at verification before any release is prepared.
        subjects = portal_fixture.snapshot_dir / "canonical" / "subjects.json"
        for parent in (portal_fixture.snapshot_dir / "canonical",):
            parent.chmod(0o700)
        subjects.chmod(0o600)
        write_json(subjects, {"subjects": []})
        from portal.errors import SnapshotVerificationError

        with pytest.raises(SnapshotVerificationError):
            prepare_release(portal_fixture)
