"""C4 release bundle preparation.

Builds the private release bundle (plan, capability manifest, plaintext
projections) and the public bundle (per-student ciphertext + metadata) under a
staging directory, then promotes it atomically to its release id.

Never publishes. Capability keys exist only in memory during preparation and in
the private capability manifest (0600 under private_root); they never reach the
public bundle, ledger, or receipts.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .canonical import (
    chmod_tree,
    compute_hash,
    encode,
    read_json,
    rmtree_readonly,
    sha256_bytes,
    write_bytes,
    write_json,
)
from .capability import (
    build_capability_url,
    generate_subject_ref,
    validate_object_id,
)
from .crypto import (
    build_canonical_aad,
    encrypt_payload,
    generate_key,
    generate_nonce,
    generate_object_id,
    b64url_encode,
)
from .errors import BundleError, BundleTamperedError
from .models import (
    PORTAL_APP_VERSION,
    PORTAL_VIEW_SCHEMA_VERSION,
    validate_publication_id,
    validate_release_id,
    validate_section_id,
)
from .plan import (
    build_release_hash_payload,
    build_release_intent,
    compute_capability_manifest_hash,
    plan_dir_for,
)
from .projection import build_projection, projection_hash, subject_student_ids
from .snapshot import verify_source_snapshot
from . import schemas as portal_schemas

METADATA_ALGORITHM = "AES-256-GCM"


@dataclass
class PreparedRelease:
    release_id: str
    release_hash: str
    release_intent_hash: str
    plan_dir: Path
    object_count: int
    capabilities: list


def _validate_projection(view: dict) -> None:
    portal_schemas.validate("student-portal-view", view)


def _validate_plan(plan_doc: dict) -> None:
    portal_schemas.validate("release-plan", plan_doc)


def _public_metadata(object_id: str, nonce_b64: str, aad_b64: str, ciphertext_sha256: str) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "algorithm": METADATA_ALGORITHM,
        "nonce": nonce_b64,
        "aad": aad_b64,
        "ciphertextSha256": ciphertext_sha256,
        "portalAppVersion": PORTAL_APP_VERSION,
    }


def _identity_inputs(identity_store, student_id: str):
    identity = identity_store.resolve(student_id) if identity_store else None
    display_name = identity.display_name if identity else None
    contact = (identity.contact or {}) if identity else {}
    contact_email = contact.get("email") or ""
    return display_name, contact_email


def _identity_projection_hash(student_id: str, display_name, contact_email: str) -> str:
    return compute_hash(
        {
            "studentId": student_id,
            "displayName": display_name,
            "contactEmail": contact_email,
        }
    )


def _prepare_object(
    *,
    release_intent,
    section_id: str,
    publication_id: str,
    student_id: str,
    snapshot_dir: Path,
    snapshot_mode: str,
    base_url: str,
    portal_mode: str,
    identity_store,
) -> dict:
    view = build_projection(section_id, publication_id, snapshot_dir, student_id, snapshot_mode)
    _validate_projection(view)
    view_hash = projection_hash(view)

    object_id = generate_object_id()
    validate_object_id(object_id)

    key = generate_key()
    nonce = generate_nonce()
    aad = build_canonical_aad(
        release_intent.release_id,
        section_id,
        publication_id,
        object_id,
        PORTAL_VIEW_SCHEMA_VERSION,
        PORTAL_APP_VERSION,
    )
    ciphertext = encrypt_payload(key, nonce, aad, encode(view))
    ciphertext_sha256 = sha256_bytes(ciphertext)

    display_name, contact_email = _identity_inputs(identity_store, student_id)
    identity_hash = _identity_projection_hash(student_id, display_name, contact_email)

    subject_ref = generate_subject_ref() if portal_mode == "authenticated" else None
    key_b64url = b64url_encode(key)
    capability_url = (
        build_capability_url(base_url, publication_id, object_id, key_b64url)
        if portal_mode == "static-encrypted"
        else None
    )

    return {
        "student_id": student_id,
        "object_id": object_id,
        "key_b64url": key_b64url,
        "nonce_b64": b64url_encode(nonce),
        "ciphertext": ciphertext,
        "ciphertext_sha256": ciphertext_sha256,
        "view": view,
        "projection_hash": view_hash,
        "identity_projection_hash": identity_hash,
        "capability_url": capability_url,
        "subject_ref": subject_ref,
        "display_name": display_name,
    }


def _stage_release(
    staging: Path,
    section_id: str,
    publication_id: str,
    release_intent,
    hosting_profile,
    portal_mode: str,
    prepared: list,
) -> dict:
    staging.mkdir(parents=True, exist_ok=True)
    os.chmod(staging, 0o700)
    (staging / "projections").mkdir(parents=True, exist_ok=True)
    (staging / "objects").mkdir(parents=True, exist_ok=True)
    public_dir = staging / "public-bundle"
    (public_dir / "objects").mkdir(parents=True, exist_ok=True)

    object_entries = []
    capability_entries = []
    public_entries = []
    for item in prepared:
        object_id = item["object_id"]
        aad = build_canonical_aad(
            release_intent.release_id,
            section_id,
            publication_id,
            object_id,
            PORTAL_VIEW_SCHEMA_VERSION,
            PORTAL_APP_VERSION,
        )
        metadata = _public_metadata(
            object_id,
            item["nonce_b64"],
            b64url_encode(aad),
            item["ciphertext_sha256"],
        )
        artifact_path = staging / "objects" / f"{object_id}.bin"
        metadata_path = staging / "objects" / f"{object_id}.metadata.json"
        write_bytes(artifact_path, item["ciphertext"])
        write_json(metadata_path, metadata)
        write_json(staging / "projections" / f"{object_id}.json", item["view"])
        write_bytes(public_dir / "objects" / f"{object_id}.bin", item["ciphertext"])
        write_json(public_dir / "objects" / f"{object_id}.metadata.json", metadata)

        object_entries.append(
            {
                "studentId": item["student_id"],
                "objectId": object_id,
                "projectionHash": item["projection_hash"],
                "artifactHash": sha256_bytes(item["ciphertext"]),
                "metadataHash": compute_hash(metadata),
            }
        )
        capability_entries.append(
            {
                "studentId": item["student_id"],
                "objectId": object_id,
                "projectionHash": item["projection_hash"],
                "identityProjectionHash": item["identity_projection_hash"],
                "capabilityUrl": item["capability_url"],
                "key": item["key_b64url"],
                "subjectRef": item["subject_ref"],
            }
        )
        public_entries.append(
            {
                "objectId": object_id,
                "artifactHash": sha256_bytes(item["ciphertext"]),
                "metadataHash": compute_hash(metadata),
                "ciphertextSha256": item["ciphertext_sha256"],
            }
        )

    public_manifest = {
        "schemaVersion": "1.0.0",
        "releaseId": release_intent.release_id,
        "publicationId": publication_id,
        "objectCount": len(public_entries),
        "objects": public_entries,
    }
    portal_schemas.validate("public-bundle-manifest", public_manifest)
    write_json(public_dir / "manifest.json", public_manifest)

    capability_manifest = {
        "schemaVersion": "1.0.0",
        "releaseId": release_intent.release_id,
        "portalMode": portal_mode,
        "entries": capability_entries,
    }
    portal_schemas.validate("capability-manifest", capability_manifest)
    write_json(staging / "capability-manifest.json", capability_manifest)
    capability_manifest_hash = compute_capability_manifest_hash(capability_manifest)
    public_bundle_manifest_hash = compute_hash(public_manifest)

    release_hash_payload = build_release_hash_payload(
        release_intent,
        object_entries,
        capability_manifest_hash,
        public_bundle_manifest_hash,
        hosting_profile,
    )
    release_hash = compute_hash(release_hash_payload)

    plan_doc = {
        "schemaVersion": "1.0.0",
        "releaseId": release_intent.release_id,
        "sectionId": section_id,
        "publicationId": publication_id,
        "portalMode": portal_mode,
        "portalAppVersion": PORTAL_APP_VERSION,
        "snapshot": release_hash_payload["snapshot"],
        "hostingProfileId": release_intent.hosting_profile_id,
        "hostingProfile": hosting_profile.to_dict(),
        "releaseHash": release_hash,
        "objectCount": len(object_entries),
        "objects": object_entries,
        "manifest": {
            "files": {
                "plan.json": {"sha256": None},
                "capability-manifest.json": {"sha256": capability_manifest_hash},
            }
        },
    }
    plan_json_bytes = encode(plan_doc)
    plan_file_hash = sha256_bytes(plan_json_bytes)
    plan_doc["manifest"]["files"]["plan.json"] = {"sha256": plan_file_hash}
    _validate_plan(plan_doc)
    write_json(staging / "plan.json", plan_doc)

    return {
        "release_hash": release_hash,
        "plan_doc": plan_doc,
    }


def prepare_release(
    *,
    roots,
    section_id: str,
    publication_id: str,
    snapshot_dir: Path,
    hosting_profile,
    portal_mode: str,
    identity_store=None,
    lifecycle_ledger=None,
) -> PreparedRelease:
    """Verify the snapshot, build and stage a release bundle, promote it.

    Process-serialized with ``_PREPARE_LOCK`` so concurrent callers racing on
    the same release either share the promoted plan (idempotent reuse) or, when
    they collide on the very first prepare, fall back to reusing the winner's
    plan instead of corrupting the staging directory.
    """
    validate_section_id(section_id)
    validate_publication_id(publication_id)

    verified = verify_source_snapshot(snapshot_dir, section_id, publication_id, lifecycle_ledger)
    hosting_profile.validate_mode_requirements()

    with _PREPARE_LOCK:
        return _prepare_release_locked(
            roots=roots,
            section_id=section_id,
            publication_id=publication_id,
            snapshot_dir=snapshot_dir,
            hosting_profile=hosting_profile,
            portal_mode=portal_mode,
            identity_store=identity_store,
            verified=verified,
        )


_PREPARE_LOCK = threading.Lock()


def _prepare_release_locked(
    *,
    roots,
    section_id: str,
    publication_id: str,
    snapshot_dir: Path,
    hosting_profile,
    portal_mode: str,
    identity_store=None,
    verified,
) -> PreparedRelease:
    release_intent = build_release_intent(
        section_id,
        publication_id,
        verified.content_hash,
        verified.review_hash,
        verified.snapshot_mode,
        PORTAL_APP_VERSION,
        hosting_profile,
        portal_mode,
    )

    plans_root = roots.private_root / "portal" / "plans"
    plan_dir = plan_dir_for(plans_root, section_id, publication_id, release_intent.release_id)
    if (plan_dir / "plan.json").exists():
        return _reuse_existing(plan_dir, release_intent, verified)

    staging = plan_dir.parent / f".staging-{release_intent.release_id}"
    if staging.exists():
        rmtree_readonly(staging)

    student_ids = subject_student_ids(snapshot_dir)
    if not student_ids:
        raise BundleError("Snapshot declares no subjects; refusing to prepare an empty release.")

    prepared = [
        _prepare_object(
            release_intent=release_intent,
            section_id=section_id,
            publication_id=publication_id,
            student_id=student_id,
            snapshot_dir=snapshot_dir,
            snapshot_mode=verified.snapshot_mode,
            base_url=hosting_profile.base_url,
            portal_mode=portal_mode,
            identity_store=identity_store,
        )
        for student_id in sorted(student_ids)
    ]

    staged = _stage_release(
        staging,
        section_id,
        publication_id,
        release_intent,
        hosting_profile,
        portal_mode,
        prepared,
    )

    plan_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(plan_dir, 0o700)
    os.rename(staging, plan_dir)
    chmod_tree(plan_dir, 0o700, 0o600)

    plan_doc = read_json(plan_dir / "plan.json")
    cap_manifest = read_json(plan_dir / "capability-manifest.json")
    capabilities = [
        {
            "studentId": entry["studentId"],
            "objectId": entry["objectId"],
            "capabilityUrl": entry.get("capabilityUrl"),
            "key": entry.get("key"),
        }
        for entry in cap_manifest["entries"]
    ]

    return PreparedRelease(
        release_id=release_intent.release_id,
        release_hash=plan_doc["releaseHash"],
        release_intent_hash=release_intent.intent_hash,
        plan_dir=plan_dir,
        object_count=len(capabilities),
        capabilities=capabilities,
    )


def _reuse_existing(plan_dir: Path, release_intent, verified) -> PreparedRelease:
    plan_doc = read_json(plan_dir / "plan.json")
    if plan_doc.get("releaseId") != release_intent.release_id:
        raise BundleTamperedError("Existing plan releaseId does not match release intent.")
    if plan_doc.get("snapshot", {}).get("contentHash") != verified.content_hash:
        raise BundleTamperedError("Existing plan references a different snapshot content hash.")
    if plan_doc.get("snapshot", {}).get("reviewHash") != verified.review_hash:
        raise BundleTamperedError("Existing plan references a different snapshot review hash.")
    _recompute_and_compare(plan_dir, plan_doc)
    cap_manifest = read_json(plan_dir / "capability-manifest.json")
    capabilities = [
        {
            "studentId": entry["studentId"],
            "objectId": entry["objectId"],
            "capabilityUrl": entry.get("capabilityUrl"),
            "key": entry.get("key"),
        }
        for entry in cap_manifest.get("entries", [])
    ]
    return PreparedRelease(
        release_id=release_intent.release_id,
        release_hash=plan_doc["releaseHash"],
        release_intent_hash=release_intent.intent_hash,
        plan_dir=plan_dir,
        object_count=len(capabilities),
        capabilities=capabilities,
    )


def _recompute_and_compare(plan_dir: Path, plan_doc: dict) -> None:
    object_entries = plan_doc["objects"]
    if plan_doc.get("objectCount") != len(object_entries):
        raise BundleTamperedError("Existing plan objectCount does not match its objects.")
    cap_manifest = read_json(plan_dir / "capability-manifest.json")
    public_manifest = read_json(plan_dir / "public-bundle" / "manifest.json")
    capability_manifest_hash = compute_capability_manifest_hash(cap_manifest)
    public_bundle_manifest_hash = compute_hash(public_manifest)
    payload = {
        "schemaVersion": "1.0.0",
        "releaseId": plan_doc["releaseId"],
        "sectionId": plan_doc["sectionId"],
        "publicationId": plan_doc["publicationId"],
        "portalMode": plan_doc["portalMode"],
        "portalAppVersion": plan_doc["portalAppVersion"],
        "snapshot": plan_doc["snapshot"],
        "hostingProfileId": plan_doc["hostingProfileId"],
        "hostingProfile": plan_doc.get("hostingProfile") or {},
        "objectCount": len(object_entries),
        "objects": object_entries,
        "capabilityManifestHash": capability_manifest_hash,
        "publicBundleManifestHash": public_bundle_manifest_hash,
    }
    actual = compute_hash(payload)
    if plan_doc["releaseHash"] != actual:
        raise BundleTamperedError("Existing plan releaseHash does not match its contents.")
