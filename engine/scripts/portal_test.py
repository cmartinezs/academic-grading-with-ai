#!/usr/bin/env python3
"""C4 self-check runner: pytest suite + Node interop + synthetic CLI E2E.

Used by ``./scripts/portal.sh test`` and CI. Exit code 0 only when the pytest
suite, the Node WebCrypto interop tests, and the CLI end-to-end scenario all
pass. The E2E builds a real approved C1 snapshot in a temp workspace and drives
the portal CLI through prepare -> approve -> publish -> verify -> status ->
revoke -> purge, asserting receipts, exit codes, and fail-closed gates.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
sys.path.insert(0, str(ENGINE))

CLI = ENGINE / "scripts" / "portal.py"


def run_unit_suite() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(ENGINE / "portal" / "tests"), "-q", "--tb=short"],
        cwd=str(ENGINE),
    )
    return result.returncode


def run_node_tests() -> int:
    node = subprocess.run(["node", "--version"], capture_output=True).returncode
    if node != 0:
        print("SKIP: node is not available; skipping static app interop tests.")
        return 0
    result = subprocess.run(
        ["node", "--test", str(ENGINE / "portal" / "static" / "tests" / "app.interop.test.js")],
        cwd=str(ENGINE / "portal" / "static"),
    )
    return result.returncode


def run_cli(env: dict, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )


def build_snapshot(base: Path, env: dict) -> None:
    from c0.identity import IdentityStore

    from publication import builder
    from publication.clock import Clock

    legacy = base / "legacy"
    roots = base / "roots"

    def write(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    course = {
        "course": {"name": "FP2111-S1", "title": "E2E"},
        "defaults": {
            "approvalThreshold": 60,
            "grading": {"minGrade": 1, "passingGrade": 4, "maxGrade": 7, "passingPercent": 60},
            "presentationWeight": 60,
            "examWeight": 40,
        },
    }
    write(legacy / "manifest.json", {"course": {"id": "FP2111-S1"}, "schemaVersion": 1})
    write(legacy / "course/course.json", course)
    write(
        legacy / "course/students.json",
        {"items": [{"id": "11111111-1", "rut": "11111111-1", "name": "Ana"}]},
    )
    write(
        legacy / "course/evaluations.json",
        {"items": [{"id": "ev1", "title": "EV1", "weight": 100, "type": "evaluacion", "forms": ["A"]}]},
    )
    write(
        legacy / "course/results.json",
        {
            "items": [
                {
                    "studentId": "11111111-1",
                    "evaluationId": "ev1",
                    "form": "A",
                    "status": "Evaluada",
                    "score": 80.0,
                    "grade": 6.0,
                    "resultPath": "x",
                    "finalFeedback": "OK",
                    "ies": [],
                }
            ]
        },
    )
    write(legacy / "course/course-summary.json", {"students": 1, "evaluations": 1})

    store = IdentityStore(roots / "state/identity")
    store.ensure_many([{"external": {"rut": "11111111-1"}, "display_name": "Ana"}])

    ctx = builder.BuildContext.resolve(
        base,
        "FP2111-S1",
        publication_id="pub_e2e01",
        env=env,
        clock=Clock(env=env),
        legacy_source=legacy,
    )
    result = builder.build_draft(ctx)
    builder.review_draft(ctx, result.review_hash, "reviewer-e2e", content_hash=result.content_hash)
    dest = builder.approve_draft(
        ctx, result.review_hash, "approver-e2e", "approve", content_hash=result.content_hash
    )
    assert dest.is_dir(), "approved snapshot must exist"


def write_profile(base: Path) -> Path:
    profile_path = base / "hosting-profile.json"
    profile = {
        "schemaVersion": "1.0.0",
        "profileId": "local-static-v1",
        "mode": "static-encrypted",
        "baseUrl": "https://portal.example.test/",
        "tlsRequired": True,
        "directoryListingDisabled": True,
        "headerPolicy": {
            "contentSecurityPolicy": "default-src 'none'; script-src 'self'; style-src 'self';",
            "referrerPolicy": "no-referrer",
            "xContentTypeOptions": "nosniff",
            "noindex": True,
        },
        "cachePolicy": {"mode": "no-store"},
        "supportsAtomicPromotion": True,
        "supportsDelete": True,
        "supportsPurge": True,
        "authorizationModel": None,
    }
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile_path


def run_e2e() -> None:
    base = Path(tempfile.mkdtemp(prefix="c4-e2e-"))
    try:
        roots = base / "roots"
        env = {
            **os.environ,
            "ACADGRAD_PRIVATE_ROOT": str(roots / "priv"),
            "ACADGRAD_STATE_ROOT": str(roots / "state"),
            "ACADGRAD_PUBLICATIONS_ROOT": str(roots / "pub"),
            "ACADGRAD_TEMP_ROOT": str(roots / "tmp"),
            "SOURCE_DATE_EPOCH": "1700000000",
        }
        build_snapshot(base, env)
        profile = write_profile(base)

        section = "FP2111-S1"
        publication = "pub_e2e01"

        # publish without confirm must fail closed (exit 1 usage gate).
        r = run_cli(env, "publish", "--section", section, "--publication", publication,
                    "--release", "prelease_" + "a" * 24, "--publisher", "local-static")
        assert r.returncode == 1, r.stdout + r.stderr

        # prepare
        r = run_cli(env, "prepare", "--section", section, "--publication", publication, "--profile", str(profile))
        assert r.returncode == 0, r.stdout + r.stderr
        prepared = json.loads(r.stdout)
        release_id = prepared["releaseId"]
        assert prepared["objectCount"] == 1, prepared

        # inspect
        r = run_cli(env, "inspect", "--section", section, "--publication", publication, "--release", release_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["releaseId"] == release_id

        # approve without confirm must fail closed (exit 1 usage gate)
        r = run_cli(env, "approve", "--section", section, "--publication", publication,
                    "--release", release_id, "--actor", "approver-e2e")
        assert r.returncode == 1, r.stdout + r.stderr

        # approve
        r = run_cli(env, "approve", "--section", section, "--publication", publication,
                    "--release", release_id, "--actor", "approver-e2e", "--confirm-reviewed")
        assert r.returncode == 0, r.stdout + r.stderr

        # publish
        r = run_cli(env, "publish", "--section", section, "--publication", publication,
                    "--release", release_id, "--publisher", "local-static", "--confirm-publish")
        assert r.returncode == 0, r.stdout + r.stderr
        published = json.loads(r.stdout)
        assert published["status"] == "published", published
        assert published["receipt"]["objectCount"] == 1, published

        # republish same release is idempotent (same receipt)
        r2 = run_cli(env, "publish", "--section", section, "--publication", publication,
                     "--release", release_id, "--publisher", "local-static", "--confirm-publish")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert json.loads(r2.stdout)["receipt"]["receiptId"] == published["receipt"]["receiptId"]

        # verify
        r = run_cli(env, "verify", "--section", section, "--publication", publication, "--release", release_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["approved"] is True

        # status
        r = run_cli(env, "status", "--release", release_id)
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["status"] == "published"

        # revoke
        r = run_cli(env, "revoke", "--section", section, "--publication", publication,
                    "--release", release_id, "--actor", "ops-e2e", "--reason", "e2e",
                    "--confirm-revoke")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["status"] == "revoked"

        # purge
        r = run_cli(env, "purge", "--section", section, "--publication", publication,
                    "--release", release_id, "--actor", "ops-e2e", "--confirm-purge")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["status"] == "purged"

        # ledger check
        r = run_cli(env, "ledger-check")
        assert r.returncode == 0, r.stdout + r.stderr

        print(f"E2E OK: {release_id} through purged")
    finally:
        for path in base.rglob("*"):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        import shutil

        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    code = run_unit_suite()
    if code != 0:
        return code
    code = run_node_tests()
    if code != 0:
        return code
    run_e2e()
    return 0


if __name__ == "__main__":
    sys.exit(main())
