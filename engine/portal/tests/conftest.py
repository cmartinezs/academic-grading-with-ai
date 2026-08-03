"""Shared C4 test fixtures.

Builds real, approved, immutable C1 Publication Snapshots (legacy-effective and
grade-policy-effective) through the canonical C1 builder, plus identity stores,
hosting profiles, and temp roots. All data is synthetic.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from c0.identity import IdentityStore
from publication import builder
from publication.clock import Clock

SECTION = "SEC-C4"
PUB_LEGACY = "pub_c4legacy"
PUB_C2 = "pub_c4c2"

RUT_A = "11111111-1"
RUT_B = "22222222-2"

STUDENTS = [
    {"id": RUT_A, "rut": RUT_A, "name": "Ana Soto"},
    {"id": RUT_B, "rut": RUT_B, "name": "Bruno Rojas"},
]

EVALUATIONS = [
    {"id": "ev1", "title": "EV1 - P1", "weight": 60, "type": "evaluacion", "forms": ["A", "B"]},
    {"id": "ev2", "title": "EV2 - P2", "weight": 40, "type": "examen"},
]

RESULTS = [
    {"studentId": RUT_A, "evaluationId": "ev1", "form": "A", "status": "Evaluada",
     "score": 70.0, "grade": 5.5, "resultPath": "x", "finalFeedback": "Buen trabajo",
     "ies": [{"id": "a1", "weightPercent": 100.0, "awardedPercent": 70.0}]},
    {"studentId": RUT_A, "evaluationId": "ev2", "form": "A", "status": "Evaluada",
     "score": 90.0, "grade": 6.5, "resultPath": "x", "finalFeedback": "Excelente", "ies": []},
    {"studentId": RUT_B, "evaluationId": "ev1", "form": "B", "status": "Evaluada",
     "score": 55.0, "grade": 4.0, "resultPath": "x", "finalFeedback": "Mejorable", "ies": []},
    {"studentId": RUT_B, "evaluationId": "ev2", "form": "B", "status": "En revisión",
     "score": None, "grade": None, "resultPath": "x", "finalFeedback": "", "ies": []},
]

COURSE = {
    "course": {"name": SECTION, "title": "C4 Fixture Course"},
    "defaults": {
        "approvalThreshold": 60,
        "grading": {"minGrade": 1, "passingGrade": 4, "maxGrade": 7, "passingPercent": 60},
        "presentationWeight": 60,
        "examWeight": 40,
    },
}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_legacy(legacy: Path, students=None) -> None:
    students = students or STUDENTS
    _write(legacy / "manifest.json", {"course": {"id": SECTION}, "schemaVersion": 1})
    _write(legacy / "course/course.json", COURSE)
    _write(legacy / "course/students.json", {"items": students})
    _write(legacy / "course/evaluations.json", {"items": EVALUATIONS})
    _write(legacy / "course/results.json", {"items": RESULTS})
    _write(legacy / "course/course-summary.json", {"students": len(students), "evaluations": 2})


def _c2_policy() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "policyId": "c4-fixture",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["ev1", "ev2"],
        "assessmentUnits": {"ev1": "percent", "ev2": "percent"},
        "stages": {
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [
                    {"ref": "ev1", "weight": "0.6"},
                    {"ref": "ev2", "weight": "0.4"},
                ],
                "missingPolicy": "zero",
            },
            "final": {
                "id": "final",
                "phase": "finalization",
                "operator": "round",
                "inputs": [{"ref": "w"}],
                "params": {"decimalPlaces": 2, "mode": "halfUp"},
            },
        },
        "resultStageId": "final",
    }


def _ensure_identity(state_root: Path, students=None) -> IdentityStore:
    students = students or STUDENTS
    store = IdentityStore(state_root / "identity")
    store.ensure_many(
        [
            {
                "external": {"rut": s["rut"]},
                "display_name": s["name"],
                "contact": {"email": f"{s['rut']}@example.test"},
            }
            for s in students
        ]
    )
    return store


def _build_snapshot(base: Path, pub: str, *, grade_policy: bool = False):
    legacy = base / "legacy"
    roots = base / "roots"
    env = {
        "ACADGRAD_PRIVATE_ROOT": str(roots / "priv"),
        "ACADGRAD_STATE_ROOT": str(roots / "state"),
        "ACADGRAD_PUBLICATIONS_ROOT": str(roots / "pub"),
        "ACADGRAD_TEMP_ROOT": str(roots / "tmp"),
        "SOURCE_DATE_EPOCH": "1700000000",
    }
    _write_legacy(legacy)
    identity_store = _ensure_identity(roots / "state")

    kwargs = {}
    if grade_policy:
        policy_file = base / "policy.json"
        _write(policy_file, _c2_policy())
        kwargs["grade_policy_source"] = policy_file

    ctx = builder.BuildContext.resolve(
        base,
        SECTION,
        publication_id=pub,
        env=env,
        clock=Clock(env=env),
        legacy_source=legacy,
        **kwargs,
    )
    result = builder.build_draft(ctx)
    builder.review_draft(
        ctx,
        result.review_hash,
        "reviewer.synthetic",
        content_hash=result.content_hash,
    )
    snapshot_dir = builder.approve_draft(
        ctx,
        result.review_hash,
        "approver.synthetic",
        "approve",
        content_hash=result.content_hash,
    )
    return roots, ctx, snapshot_dir, identity_store


@dataclass
class PortalFixture:
    base: Path
    roots: Path
    section_id: str
    publication_id: str
    snapshot_dir: Path
    lifecycle_ledger: object
    identity_store: IdentityStore
    portal_mode: str
    hosting_profile: object
    ledger: object
    snapshot_mode: str


def _static_profile() -> dict:
    return {
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


def _authenticated_profile() -> dict:
    profile = _static_profile()
    profile.update(
        {
            "profileId": "fake-auth-v1",
            "mode": "authenticated",
            "authorizationModel": "subject-bound",
        }
    )
    profile["cachePolicy"] = {"mode": "private-no-store"}
    profile["headerPolicy"]["crossStudentAccess"] = "denied"
    return profile


def _hosting_profile(data: dict):
    from portal.models import HostingProfile

    return HostingProfile(
        profile_id=data["profileId"],
        mode=data["mode"],
        base_url=data["baseUrl"],
        tls_required=data["tlsRequired"],
        directory_listing_disabled=data["directoryListingDisabled"],
        header_policy=data["headerPolicy"],
        cache_policy=data["cachePolicy"],
        supports_atomic_promotion=data["supportsAtomicPromotion"],
        supports_delete=data["supportsDelete"],
        supports_purge=data["supportsPurge"],
        authorization_model=data.get("authorizationModel"),
    )


@pytest.fixture
def portal_fixture(tmp_path):
    """Real approved legacy-effective snapshot + identity + profile + ledger."""
    from portal.ledger import PortalLedger

    base = tmp_path / "base"
    roots, ctx, snapshot_dir, identity_store = _build_snapshot(base, PUB_LEGACY)
    ledger = PortalLedger(roots / "state" / "portal" / "portal-ledger.sqlite3")
    ledger.init()
    fixture = PortalFixture(
        base=base,
        roots=roots,
        section_id=SECTION,
        publication_id=PUB_LEGACY,
        snapshot_dir=snapshot_dir,
        lifecycle_ledger=ctx.ledger(),
        identity_store=identity_store,
        portal_mode="static-encrypted",
        hosting_profile=_hosting_profile(_static_profile()),
        ledger=ledger,
        snapshot_mode="legacy-effective",
    )
    yield fixture
    ledger.close()


@pytest.fixture
def c2_fixture(tmp_path):
    """Real approved grade-policy-effective snapshot."""
    from portal.ledger import PortalLedger

    base = tmp_path / "base"
    roots, ctx, snapshot_dir, identity_store = _build_snapshot(
        base, PUB_C2, grade_policy=True
    )
    ledger = PortalLedger(roots / "state" / "portal" / "portal-ledger.sqlite3")
    ledger.init()
    fixture = PortalFixture(
        base=base,
        roots=roots,
        section_id=SECTION,
        publication_id=PUB_C2,
        snapshot_dir=snapshot_dir,
        lifecycle_ledger=ctx.ledger(),
        identity_store=identity_store,
        portal_mode="static-encrypted",
        hosting_profile=_hosting_profile(_static_profile()),
        ledger=ledger,
        snapshot_mode="grade-policy-effective",
    )
    yield fixture
    ledger.close()


@pytest.fixture
def auth_fixture(tmp_path):
    """Real approved legacy-effective snapshot with an authenticated profile."""
    from portal.ledger import PortalLedger

    base = tmp_path / "auth_base"
    roots, ctx, snapshot_dir, identity_store = _build_snapshot(base, PUB_LEGACY)
    ledger = PortalLedger(roots / "state" / "portal" / "portal-ledger.sqlite3")
    ledger.init()
    fixture = PortalFixture(
        base=base,
        roots=roots,
        section_id=SECTION,
        publication_id=PUB_LEGACY,
        snapshot_dir=snapshot_dir,
        lifecycle_ledger=ctx.ledger(),
        identity_store=identity_store,
        portal_mode="authenticated",
        hosting_profile=_hosting_profile(_authenticated_profile()),
        ledger=ledger,
        snapshot_mode="legacy-effective",
    )
    yield fixture
    ledger.close()
