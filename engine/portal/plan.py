"""C4 release intent hashing and release plan assembly.

``releaseId`` encodes logical intent only (snapshot + profile + app + mode), never
student data. ``releaseHash`` additionally binds every projection, object binding,
ciphertext, metadata, and manifest so that any change invalidates the hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .canonical import compute_hash
from .errors import ValidationError
from .models import validate_publication_id, validate_section_id

RELEASE_ID_PREFIX = "prelease_"


def compute_release_intent_hash(
    section_id: str,
    publication_id: str,
    snapshot_content_hash: str,
    snapshot_review_hash: str,
    snapshot_mode: str,
    portal_app_version: str,
    hosting_profile_hash: str,
    portal_mode: str,
) -> str:
    validate_section_id(section_id)
    validate_publication_id(publication_id)
    if not snapshot_content_hash or not snapshot_review_hash:
        raise ValidationError("Snapshot hashes are required for release intent.")
    if snapshot_mode not in ("legacy-effective", "grade-policy-effective"):
        raise ValidationError(f"Invalid snapshot mode: {snapshot_mode!r}")
    if portal_mode not in ("static-encrypted", "authenticated"):
        raise ValidationError(f"Invalid portal mode: {portal_mode!r}")
    material = "".join(
        [
            section_id,
            publication_id,
            snapshot_content_hash,
            snapshot_review_hash,
            snapshot_mode,
            portal_app_version,
            hosting_profile_hash,
            portal_mode,
        ]
    )
    from .canonical import sha256_text

    return sha256_text(material)


def release_id_from_intent(intent_hash: str) -> str:
    if not isinstance(intent_hash, str) or len(intent_hash) < 24:
        raise ValidationError("Invalid releaseIntentHash.")
    return RELEASE_ID_PREFIX + intent_hash[:24]


def compute_capability_manifest_hash(manifest_doc: dict) -> str:
    """SHA-256 of the capability manifest canonical JSON excluding key material."""
    stripped = {
        "schemaVersion": manifest_doc.get("schemaVersion"),
        "releaseId": manifest_doc.get("releaseId"),
        "portalMode": manifest_doc.get("portalMode"),
        "entries": [
            {
                "studentId": entry["studentId"],
                "objectId": entry["objectId"],
                "projectionHash": entry["projectionHash"],
                "identityProjectionHash": entry["identityProjectionHash"],
                "capabilityUrl": entry.get("capabilityUrl"),
                "subjectRef": entry.get("subjectRef"),
            }
            for entry in manifest_doc.get("entries", [])
        ],
    }
    return compute_hash(stripped)


@dataclass(frozen=True)
class ReleaseIntent:
    intent_hash: str
    release_id: str
    section_id: str
    publication_id: str
    snapshot_content_hash: str
    snapshot_review_hash: str
    snapshot_mode: str
    portal_app_version: str
    hosting_profile_id: str
    hosting_profile_hash: str
    portal_mode: str


def build_release_intent(
    section_id: str,
    publication_id: str,
    snapshot_content_hash: str,
    snapshot_review_hash: str,
    snapshot_mode: str,
    portal_app_version: str,
    hosting_profile,
    portal_mode: str,
) -> ReleaseIntent:
    intent_hash = compute_release_intent_hash(
        section_id,
        publication_id,
        snapshot_content_hash,
        snapshot_review_hash,
        snapshot_mode,
        portal_app_version,
        hosting_profile.profile_hash,
        portal_mode,
    )
    return ReleaseIntent(
        intent_hash=intent_hash,
        release_id=release_id_from_intent(intent_hash),
        section_id=section_id,
        publication_id=publication_id,
        snapshot_content_hash=snapshot_content_hash,
        snapshot_review_hash=snapshot_review_hash,
        snapshot_mode=snapshot_mode,
        portal_app_version=portal_app_version,
        hosting_profile_id=hosting_profile.profile_id,
        hosting_profile_hash=hosting_profile.profile_hash,
        portal_mode=portal_mode,
    )


def build_release_hash_payload(
    release_intent: ReleaseIntent,
    object_entries: list,
    capability_manifest_hash: str,
    public_bundle_manifest_hash: str,
    hosting_profile=None,
) -> dict:
    payload = {
        "schemaVersion": "1.0.0",
        "releaseId": release_intent.release_id,
        "sectionId": release_intent.section_id,
        "publicationId": release_intent.publication_id,
        "portalMode": release_intent.portal_mode,
        "portalAppVersion": release_intent.portal_app_version,
        "snapshot": {
            "contentHash": release_intent.snapshot_content_hash,
            "reviewHash": release_intent.snapshot_review_hash,
            "mode": release_intent.snapshot_mode,
        },
        "hostingProfileId": release_intent.hosting_profile_id,
        "hostingProfile": hosting_profile.to_dict() if hosting_profile is not None else {},
        "objectCount": len(object_entries),
        "objects": [
            {
                "studentId": entry["studentId"],
                "objectId": entry["objectId"],
                "projectionHash": entry["projectionHash"],
                "artifactHash": entry["artifactHash"],
                "metadataHash": entry["metadataHash"],
            }
            for entry in object_entries
        ],
        "capabilityManifestHash": capability_manifest_hash,
        "publicBundleManifestHash": public_bundle_manifest_hash,
    }
    return payload


def plan_dir_for(plans_root: Path, section_id: str, publication_id: str, release_id: str) -> Path:
    return Path(plans_root) / section_id / publication_id / release_id
