"""C4 JSON Schema contract tests."""

from __future__ import annotations

import pytest

from portal import schemas as portal_schemas
from portal.errors import SchemaValidationError


def test_view_valid():
    portal_schemas.validate(
        "student-portal-view",
        {
            "schemaVersion": "1.0.0",
            "sectionId": "SEC-C4",
            "publicationId": "pub_c4",
            "studentId": "stu_1",
            "snapshotMode": "legacy-effective",
            "assessments": [
                {"assessmentId": "ev1", "label": "P1", "status": "Evaluada",
                 "score": "70.0", "grade": "5.5", "unit": "percent", "feedback": "ok"}
            ],
            "finalOutcome": None,
            "generatedFrom": "student-portal/projection/v1",
        },
    )


def test_view_rejects_float_scores():
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate(
            "student-portal-view",
            {
                "schemaVersion": "1.0.0",
                "sectionId": "SEC-C4",
                "publicationId": "pub_c4",
                "studentId": "stu_1",
                "snapshotMode": "legacy-effective",
                "assessments": [
                    {"assessmentId": "ev1", "label": "P1", "status": "Evaluada",
                     "score": 70.0}
                ],
                "finalOutcome": None,
                "generatedFrom": "student-portal/projection/v1",
            },
        )


def test_view_rejects_extra_keys():
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate(
            "student-portal-view",
            {
                "schemaVersion": "1.0.0",
                "sectionId": "SEC-C4",
                "publicationId": "pub_c4",
                "studentId": "stu_1",
                "snapshotMode": "legacy-effective",
                "assessments": [],
                "finalOutcome": None,
                "generatedFrom": "x",
                "capabilityKey": "nope",
            },
        )


def test_view_c2_final_outcome():
    portal_schemas.validate(
        "student-portal-view",
        {
            "schemaVersion": "1.0.0",
            "sectionId": "SEC-C4",
            "publicationId": "pub_c4",
            "studentId": "stu_1",
            "snapshotMode": "grade-policy-effective",
            "assessments": [],
            "finalOutcome": {
                "value": "6.4",
                "unit": "grade",
                "resultState": "finalized",
                "finalizable": True,
            },
            "generatedFrom": "x",
        },
    )


def test_plan_valid():
    portal_schemas.validate(
        "release-plan",
        {
            "schemaVersion": "1.0.0",
            "releaseId": "prelease_" + "a" * 24,
            "sectionId": "SEC-C4",
            "publicationId": "pub_c4",
            "portalMode": "static-encrypted",
            "portalAppVersion": "1.0.0",
            "snapshot": {"contentHash": "c" * 64, "reviewHash": "f" * 64, "mode": "legacy-effective"},
            "hostingProfileId": "local-static-v1",
            "hostingProfile": {"profileId": "local-static-v1"},
            "releaseHash": "f" * 64,
            "objectCount": 1,
            "objects": [
                {"studentId": "stu_1", "objectId": "o" * 32,
                 "projectionHash": "5" * 64, "artifactHash": "7" * 64, "metadataHash": "9" * 64}
            ],
            "manifest": {"files": {}},
        },
    )


def test_plan_rejects_key_in_objects():
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate(
            "release-plan",
            {
                "schemaVersion": "1.0.0",
                "releaseId": "prelease_" + "a" * 24,
                "sectionId": "SEC-C4",
                "publicationId": "pub_c4",
                "portalMode": "static-encrypted",
                "portalAppVersion": "1.0.0",
            "snapshot": {"contentHash": "c" * 64, "reviewHash": "f" * 64, "mode": "legacy-effective"},
                "hostingProfileId": "local-static-v1",
                "hostingProfile": {"profileId": "local-static-v1"},
                "releaseHash": "f" * 64,
                "objectCount": 1,
                "objects": [
                    {"studentId": "stu_1", "objectId": "o" * 32,
                     "projectionHash": "5" * 64, "artifactHash": "7" * 64,
                     "metadataHash": "9" * 64, "key": "secret"}
                ],
                "manifest": {"files": {}},
            },
        )


def test_profile_valid_and_invalid():
    valid = {
        "schemaVersion": "1.0.0",
        "profileId": "local-static-v1",
        "mode": "static-encrypted",
        "baseUrl": "https://portal.example.test/",
        "tlsRequired": True,
        "directoryListingDisabled": True,
        "headerPolicy": {},
        "cachePolicy": {"mode": "no-store"},
        "supportsAtomicPromotion": True,
        "supportsDelete": True,
        "supportsPurge": True,
    }
    portal_schemas.validate("hosting-profile", valid)
    bad = dict(valid)
    bad["tlsRequired"] = False
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate("hosting-profile", bad)


def test_approval_valid_and_invalid():
    valid = {
        "schemaVersion": "1.0.0",
        "releaseId": "prelease_" + "a" * 24,
        "releaseHash": "f" * 64,
        "objectCount": 1,
        "approvedBy": "user.approver",
        "approvedAt": "2026-08-03T00:00:00Z",
        "confirmation": "confirm-reviewed",
        "status": "approved",
    }
    portal_schemas.validate("approval", valid)
    bad = dict(valid)
    bad["confirmation"] = "something-else"
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate("approval", bad)


def test_capability_manifest_valid_and_rejects_key_outside_manifest():
    valid = {
        "schemaVersion": "1.0.0",
        "releaseId": "prelease_" + "a" * 24,
        "portalMode": "static-encrypted",
        "entries": [
            {"studentId": "stu_1", "objectId": "o" * 32,
             "projectionHash": "5" * 64, "identityProjectionHash": "6" * 64,
             "capabilityUrl": None, "key": "K", "subjectRef": None}
        ],
    }
    portal_schemas.validate("capability-manifest", valid)
    bad = dict(valid)
    bad["key"] = "leak"
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate("capability-manifest", bad)


def test_receipt_valid():
    portal_schemas.validate(
        "receipt",
        {
            "receiptId": "rcpt_abc",
            "type": "publish",
            "releaseId": "prelease_" + "a" * 24,
            "releaseHash": "f" * 64,
            "hostingProfileId": "local-static-v1",
            "publisherType": "local-static",
            "objectCount": 1,
            "createdAt": "2026-08-03T00:00:00Z",
        },
    )


def test_public_bundle_manifest_valid():
    portal_schemas.validate(
        "public-bundle-manifest",
        {
            "schemaVersion": "1.0.0",
            "releaseId": "prelease_" + "a" * 24,
            "publicationId": "pub_c4",
            "objectCount": 1,
            "objects": [
                {"objectId": "o" * 32, "artifactHash": "a" * 64,
                 "metadataHash": "9" * 64, "ciphertextSha256": "c" * 64}
            ],
        },
    )


def test_unknown_schema_fails_closed():
    with pytest.raises(SchemaValidationError):
        portal_schemas.validate("does-not-exist", {})
