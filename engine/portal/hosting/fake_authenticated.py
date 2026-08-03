"""Reference/fake authenticated publisher for C4 authenticated mode.

Implements the authenticated adapter contract with subject-bound authorization.
This is a reference adapter for contract testing only; it is not a production
hosting provider (the limit is documented, not hidden). It never exposes a
global listing and denies anonymous access.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..canonical import read_json, write_bytes, write_json, rmtree_readonly
from ..errors import PublisherError
from ..models import HostingProfile
from .base import (
    AbstractPublisher,
    PreflightError,
    PublishResult,
    PurgeResult,
    RevokeResult,
    preflight_bundle,
    preflight_ledger,
    preflight_profile,
)


class FakeAuthenticatedPublisher(AbstractPublisher):
    """Reference adapter: stores subject-bound projections on local disk."""

    publisher_type = "fake-authenticated"

    def preflight(self, profile: HostingProfile, plan_dir: Path, ledger) -> None:
        preflight_profile(profile)
        preflight_ledger(ledger)
        plan_doc = preflight_bundle(plan_dir)
        if plan_doc.get("portalMode") != "authenticated":
            raise PreflightError("fake-authenticated only serves authenticated releases.")
        if profile.authorization_model != "subject-bound":
            raise PreflightError("authenticated mode requires subject-bound authorization.")
        if not profile.supports_delete or not profile.supports_purge:
            raise PreflightError("fake-authenticated requires delete and purge support.")

    def _store_dir(self, deployments_root: Path, plan_doc: dict) -> Path:
        return (
            Path(deployments_root)
            / plan_doc["sectionId"]
            / plan_doc["publicationId"]
            / plan_doc["releaseId"]
            / "subjects"
        )

    def _subject_map(self, plan_dir: Path) -> dict:
        cap_manifest = read_json(Path(plan_dir) / "capability-manifest.json")
        mapping = {}
        for entry in cap_manifest.get("entries", []):
            subject_ref = entry.get("subjectRef")
            if subject_ref:
                mapping[subject_ref] = entry
        return mapping

    def publish(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
                deployments_root: Path) -> PublishResult:
        self.preflight(self._profile_from_plan(plan_doc), plan_dir, ledger)
        store = self._store_dir(deployments_root, plan_doc)
        staging = store.parent / f".staging-{plan_doc['releaseId']}"
        if staging.exists():
            rmtree_readonly(staging)
        staging.mkdir(parents=True, exist_ok=True)
        os.chmod(staging, 0o700)

        subject_map = self._subject_map(plan_dir)
        public_manifest = read_json(Path(plan_dir) / "public-bundle" / "manifest.json")
        count = 0
        for entry in public_manifest["objects"]:
            object_id = entry["objectId"]
            subject_entry = next(
                (s for s in subject_map.values() if s["objectId"] == object_id), None
            )
            if subject_entry is None or not subject_entry.get("subjectRef"):
                raise PreflightError(f"object {object_id} has no subject ref.")
            subject_ref = subject_entry["subjectRef"]
            projection = read_json(Path(plan_dir) / "projections" / f"{object_id}.json")
            write_json(staging / f"{subject_ref}.json", projection)
            write_bytes(staging / f"{subject_ref}.metadata", str(entry["artifactHash"]).encode())
            count += 1

        if store.exists():
            rmtree_readonly(store)
        store.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(store)
        os.chmod(store, 0o700)
        return PublishResult(
            deployment_reference=str(store),
            artifact_manifest_hash=str(count),
            object_count=count,
        )

    def verify_subject_access(self, subject_ref: str, reference: str, profile: HostingProfile) -> bool:
        if not subject_ref or not reference:
            return False
        return subject_ref == reference

    def revoke(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
               deployments_root: Path, actor: str, reason: Optional[str]) -> RevokeResult:
        store = self._store_dir(deployments_root, plan_doc)
        subject_map = self._subject_map(plan_dir)
        removed = 0
        unavailable = 0
        for subject_ref in subject_map:
            target = store / f"{subject_ref}.json"
            if target.exists():
                target.unlink()
                removed += 1
            else:
                unavailable += 1
        return RevokeResult(removed_objects=removed, unavailable_objects=unavailable)

    def purge(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
              deployments_root: Path, actor: str) -> PurgeResult:
        store = self._store_dir(deployments_root, plan_doc)
        subject_map = self._subject_map(plan_dir)
        removed = 0
        missing = 0
        for subject_ref in subject_map:
            target = store / f"{subject_ref}.json"
            if target.exists():
                target.unlink()
                removed += 1
            else:
                missing += 1
        if store.exists() and not any(store.iterdir()):
            store.rmdir()
        return PurgeResult(removed_objects=removed, missing_objects=missing)

    def _profile_from_plan(self, plan_doc: dict) -> HostingProfile:
        from ..models import HostingProfile as HP

        hp = plan_doc["hostingProfile"]
        return HP(
            profile_id=plan_doc["hostingProfileId"],
            mode=plan_doc["portalMode"],
            base_url=hp["baseUrl"],
            tls_required=hp["tlsRequired"],
            directory_listing_disabled=hp["directoryListingDisabled"],
            header_policy=hp["headerPolicy"],
            cache_policy=hp["cachePolicy"],
            supports_atomic_promotion=hp["supportsAtomicPromotion"],
            supports_delete=hp["supportsDelete"],
            supports_purge=hp["supportsPurge"],
            authorization_model=hp.get("authorizationModel"),
        )
