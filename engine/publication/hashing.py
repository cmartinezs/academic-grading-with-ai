"""C1 hash scheme: per-file artifact, content and review hashes (P0 hashes).

Three layers (see ADR-0011 update):

1. Artifact hash   — sha256 of each declared file, recorded in manifest.files.
2. contentHash     — logical content over canonical/provenance files, with
                     volatile operational keys (build time) stripped. Invariant
                     across rebuilds with different timestamps.
3. reviewHash      — binds contentHash to the immutable manifest core
                     (identity, lineage, engine/adapter/policy versions) plus
                     per-file classification/audience. What a reviewer signs.
"""

from __future__ import annotations

from .jsonutil import compute_content_hash, encode, serialize, sha256_bytes

CLASSIFICATION_INTERNAL = "INTERNAL"
CLASSIFICATION_CONFIDENTIAL = "CONFIDENTIAL"
CLASSIFICATION_RESTRICTED = "RESTRICTED"

AUDIENCE_INTERNAL = "internal"
AUDIENCE_STAFF = "staff"
AUDIENCE_GRADING = "grading"

VALID_CLASSIFICATIONS = frozenset(
    {CLASSIFICATION_INTERNAL, CLASSIFICATION_CONFIDENTIAL, CLASSIFICATION_RESTRICTED}
)
VALID_AUDIENCES = frozenset({AUDIENCE_INTERNAL, AUDIENCE_STAFF, AUDIENCE_GRADING})

# Classification / audience per snapshot rel path (P0 classification, items 30-31).
# INTERNAL: technical/operational; CONFIDENTIAL: source hashes and approvals;
# RESTRICTED: student-scoped canonical data.
EXPECTED_FILE_META = {
    "manifest.json": (CLASSIFICATION_INTERNAL, AUDIENCE_INTERNAL),
    "canonical/section.json": (CLASSIFICATION_INTERNAL, AUDIENCE_INTERNAL),
    "canonical/assessments.json": (CLASSIFICATION_INTERNAL, AUDIENCE_INTERNAL),
    "canonical/subjects.json": (CLASSIFICATION_RESTRICTED, AUDIENCE_GRADING),
    "canonical/results.json": (CLASSIFICATION_RESTRICTED, AUDIENCE_GRADING),
    "canonical/policy.json": (CLASSIFICATION_RESTRICTED, AUDIENCE_GRADING),
    "provenance/source-hashes.json": (CLASSIFICATION_CONFIDENTIAL, AUDIENCE_STAFF),
    "provenance/engine.json": (CLASSIFICATION_INTERNAL, AUDIENCE_INTERNAL),
    "provenance/migrations.json": (CLASSIFICATION_INTERNAL, AUDIENCE_INTERNAL),
    "approvals/review.json": (CLASSIFICATION_CONFIDENTIAL, AUDIENCE_STAFF),
    "approvals/publication-approval.json": (CLASSIFICATION_CONFIDENTIAL, AUDIENCE_STAFF),
}


def expected_file_meta(rel: str):
    return EXPECTED_FILE_META.get(rel)


def content_hashes_from_payloads(payloads: dict[str, object]) -> dict[str, str]:
    """Per-file sha256 for an in-memory dict of {rel path: payload}."""
    return {
        rel: sha256_bytes(encode(payload))
        for rel, payload in sorted(payloads.items())
    }


def content_hash_from_payloads(payloads: dict[str, object]) -> str:
    return compute_content_hash(content_hashes_from_payloads(payloads))


def review_hash(content_hash: str, core: dict, file_entries: dict[str, dict]) -> str:
    """Review hash over the immutable manifest core + content file hashes.

    `core` must carry sectionId, publicationId, supersedesPublicationId,
    correctsPublicationId, engineVersion, adapterVersion and
    policySnapshotVersion. `file_entries` maps a content rel path to
    {"sha256", "classification", "audience"}.
    """
    payload = {
        "contentHash": content_hash,
        "sectionId": core["sectionId"],
        "publicationId": core["publicationId"],
        "supersedesPublicationId": core.get("supersedesPublicationId"),
        "correctsPublicationId": core.get("correctsPublicationId"),
        "engineVersion": core["engineVersion"],
        "adapterVersion": core["adapterVersion"],
        "policySnapshotVersion": core["policySnapshotVersion"],
        "files": {
            rel: {
                "sha256": entry["sha256"],
                "classification": entry["classification"],
                "audience": entry["audience"],
            }
            for rel, entry in sorted(file_entries.items())
        },
    }
    return sha256_bytes(encode(payload))


def content_file_entries(files: dict[str, dict]) -> dict[str, dict]:
    """Subset of manifest.files entries that participate in the content/review hash."""
    return {
        rel: entry
        for rel, entry in files.items()
        if rel.startswith("canonical/") or rel.startswith("provenance/")
    }
