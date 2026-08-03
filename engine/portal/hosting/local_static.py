"""Local static publisher for C4 static-encrypted mode.

Deploys the public bundle (per-student encrypted artifacts plus the static app)
under ``state_root/portal/deployments/<sectionId>/<publicationId>/<releaseId>/``
with atomic promotion. It is the reference implementation and the one tested
end-to-end; it never sees capability keys.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..canonical import compute_hash, read_json, sha256_file, write_json, rmtree_readonly
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
    preflight_snapshot,
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

STATIC_FILES = ("index.html", "app.js", "styles.css")


class LocalStaticPublisher(AbstractPublisher):
    publisher_type = "local-static"

    def preflight(self, profile: HostingProfile, plan_dir: Path, ledger) -> None:
        preflight_profile(profile)
        preflight_ledger(ledger)
        plan_doc = preflight_bundle(plan_dir)
        if plan_doc.get("portalMode") != "static-encrypted":
            raise PreflightError("local-static publisher only serves static-encrypted releases.")
        if not profile.supports_atomic_promotion:
            raise PreflightError("local-static requires atomic promotion support.")
        if not profile.supports_delete or not profile.supports_purge:
            raise PreflightError("local-static requires delete and purge support.")

    def _deployment_dir(self, deployments_root: Path, plan_doc: dict) -> Path:
        return (
            Path(deployments_root)
            / plan_doc["sectionId"]
            / plan_doc["publicationId"]
            / plan_doc["releaseId"]
        )

    def _stage_public(self, plan_dir: Path, plan_doc: dict, deployments_root: Path) -> Path:
        source = Path(plan_dir) / "public-bundle"
        if not (source / "manifest.json").exists():
            raise PreflightError("public-bundle manifest missing.")
        deployment = self._deployment_dir(deployments_root, plan_doc)
        staging = deployment.parent / f".staging-{plan_doc['releaseId']}"
        if staging.exists():
            rmtree_readonly(staging)
        staging.mkdir(parents=True, exist_ok=True)
        os.chmod(staging, 0o700)

        manifest = read_json(source / "manifest.json")
        for entry in manifest["objects"]:
            object_id = entry["objectId"]
            obj_dir = staging / object_id
            obj_dir.mkdir(parents=True, exist_ok=True)
            for name in STATIC_FILES:
                src = STATIC_DIR / name
                if not src.exists():
                    raise PreflightError(f"static asset missing: {name}")
                (obj_dir / name).write_bytes(src.read_bytes())
            payload = (source / "objects" / f"{object_id}.bin").read_bytes()
            (obj_dir / "payload.enc").write_bytes(payload)
            metadata = read_json(source / "objects" / f"{object_id}.metadata.json")
            write_json(obj_dir / "metadata.json", metadata)
        write_json(staging / "manifest.json", manifest)
        return staging

    def publish(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
                deployments_root: Path) -> PublishResult:
        self.preflight(self._profile_from_plan(plan_doc), plan_dir, ledger)
        deployment = self._deployment_dir(deployments_root, plan_doc)
        staging = self._stage_public(plan_dir, plan_doc, deployments_root)
        if deployment.exists():
            rmtree_readonly(deployment)
        deployment.mkdir(parents=True, exist_ok=True)
        os.rename(staging, deployment)
        manifest = read_json(deployment / "manifest.json")
        artifact_manifest_hash = sha256_file(deployment / "manifest.json")
        return PublishResult(
            deployment_reference=str(deployment),
            artifact_manifest_hash=artifact_manifest_hash,
            object_count=manifest["objectCount"],
        )

    def revoke(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
               deployments_root: Path, actor: str, reason: Optional[str]) -> RevokeResult:
        deployment = self._deployment_dir(deployments_root, plan_doc)
        manifest = read_json(plan_dir / "public-bundle" / "manifest.json")
        requested = manifest["objectCount"]
        removed = 0
        unavailable = 0
        for entry in manifest["objects"]:
            obj_dir = deployment / entry["objectId"]
            if obj_dir.exists():
                rmtree_readonly(obj_dir)
                removed += 1
            else:
                unavailable += 1
        return RevokeResult(removed_objects=removed, unavailable_objects=unavailable)

    def purge(self, *, plan_dir: Path, plan_doc: dict, ledger, receipts_dir: Path,
              deployments_root: Path, actor: str) -> PurgeResult:
        deployment = self._deployment_dir(deployments_root, plan_doc)
        manifest = read_json(plan_dir / "public-bundle" / "manifest.json")
        missing = 0
        removed = 0
        for entry in manifest["objects"]:
            obj_dir = deployment / entry["objectId"]
            if obj_dir.exists():
                rmtree_readonly(obj_dir)
                removed += 1
            else:
                missing += 1
        if deployment.exists() and not any(deployment.iterdir()):
            deployment.rmdir()
        return PurgeResult(removed_objects=removed, missing_objects=missing)

    def _profile_from_plan(self, plan_doc: dict) -> HostingProfile:
        from ..models import HostingProfile as HP

        return HP(
            profile_id=plan_doc["hostingProfileId"],
            mode=plan_doc["portalMode"],
            base_url=plan_doc["hostingProfile"]["baseUrl"],
            tls_required=plan_doc["hostingProfile"]["tlsRequired"],
            directory_listing_disabled=plan_doc["hostingProfile"]["directoryListingDisabled"],
            header_policy=plan_doc["hostingProfile"]["headerPolicy"],
            cache_policy=plan_doc["hostingProfile"]["cachePolicy"],
            supports_atomic_promotion=plan_doc["hostingProfile"]["supportsAtomicPromotion"],
            supports_delete=plan_doc["hostingProfile"]["supportsDelete"],
            supports_purge=plan_doc["hostingProfile"]["supportsPurge"],
            authorization_model=plan_doc["hostingProfile"].get("authorizationModel"),
        )
