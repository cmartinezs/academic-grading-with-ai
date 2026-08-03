"""C4 portal domain models (dataclasses).

Persisted contracts are plain JSON documents; these dataclasses are thin,
validated views used by the domain operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .errors import HostingProfileError

SECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PUBLICATION_ID_RE = re.compile(r"^pub_[A-Za-z0-9]{1,64}$")
RELEASE_ID_RE = re.compile(r"^prelease_[0-9a-f]{24}$")
OBJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
STUDENT_ID_RE = re.compile(r"^stu_[A-Za-z0-9]{1,64}$")

PORTAL_MODES = ("static-encrypted", "authenticated")
SNAPSHOT_MODES = ("legacy-effective", "grade-policy-effective")

PORTAL_APP_VERSION = "1.0.0"
PORTAL_VIEW_SCHEMA_VERSION = "1.0.0"


def validate_section_id(section_id: str) -> str:
    if not isinstance(section_id, str) or not SECTION_ID_RE.match(section_id):
        raise HostingProfileError(f"Invalid sectionId: {section_id!r}")
    return section_id


def validate_publication_id(publication_id: str) -> str:
    if not isinstance(publication_id, str) or not PUBLICATION_ID_RE.match(publication_id):
        raise HostingProfileError(f"Invalid publicationId: {publication_id!r}")
    return publication_id


def validate_release_id(release_id: str) -> str:
    if not isinstance(release_id, str) or not RELEASE_ID_RE.match(release_id):
        raise HostingProfileError(f"Invalid releaseId: {release_id!r}")
    return release_id


def validate_actor(actor: str) -> str:
    if not isinstance(actor, str) or not actor:
        raise HostingProfileError("Actor must be a non-empty opaque audit identifier.")
    if "@" in actor:
        raise HostingProfileError("Actor must not be an email address.")
    if not ACTOR_RE.match(actor):
        raise HostingProfileError("Actor contains unsupported characters.")
    return actor


@dataclass(frozen=True)
class HostingProfile:
    """Validated PortalHostingProfile V1."""

    profile_id: str
    mode: str
    base_url: str
    tls_required: bool
    directory_listing_disabled: bool
    header_policy: dict
    cache_policy: dict
    supports_atomic_promotion: bool
    supports_delete: bool
    supports_purge: bool
    authorization_model: Optional[str] = None
    schema_version: str = "1.0.0"

    @property
    def profile_hash(self) -> str:
        from .canonical import compute_hash

        return compute_hash(self.to_dict())

    def to_dict(self) -> dict:
        payload = {
            "schemaVersion": self.schema_version,
            "profileId": self.profile_id,
            "mode": self.mode,
            "baseUrl": self.base_url,
            "tlsRequired": self.tls_required,
            "directoryListingDisabled": self.directory_listing_disabled,
            "headerPolicy": dict(self.header_policy),
            "cachePolicy": dict(self.cache_policy),
            "supportsAtomicPromotion": self.supports_atomic_promotion,
            "supportsDelete": self.supports_delete,
            "supportsPurge": self.supports_purge,
        }
        if self.authorization_model is not None:
            payload["authorizationModel"] = self.authorization_model
        return payload

    def validate_mode_requirements(self) -> None:
        """Fail closed when the profile does not satisfy its mode requirements."""
        if self.mode not in PORTAL_MODES:
            raise HostingProfileError(f"Unsupported portal mode: {self.mode!r}")
        if not self.tls_required:
            raise HostingProfileError("TLS is required for every C4 portal mode.")
        if not self.directory_listing_disabled:
            raise HostingProfileError("Directory listing must be disabled.")
        if self.mode == "static-encrypted":
            if self.authorization_model is not None:
                raise HostingProfileError(
                    "static-encrypted must not declare an authorizationModel."
                )
            self._require_header("noindex", True)
            self._require_header("referrerPolicy", "no-referrer")
            self._require_header("xContentTypeOptions", "nosniff")
            if not self.header_policy.get("contentSecurityPolicy"):
                raise HostingProfileError(
                    "static-encrypted requires a Content-Security-Policy."
                )
            cache_mode = (self.cache_policy or {}).get("mode")
            if cache_mode not in ("no-store", "no-cache", "private"):
                raise HostingProfileError(
                    "static-encrypted requires an explicit cache policy."
                )
        if self.mode == "authenticated":
            if self.authorization_model != "subject-bound":
                raise HostingProfileError(
                    "authenticated requires authorizationModel = subject-bound."
                )
            cache_mode = (self.cache_policy or {}).get("mode")
            if cache_mode != "private-no-store":
                raise HostingProfileError(
                    "authenticated requires cachePolicy.mode = private-no-store."
                )
            if self.header_policy.get("crossStudentAccess") != "denied":
                raise HostingProfileError(
                    "authenticated requires crossStudentAccess = denied."
                )
            self._require_header("referrerPolicy", "no-referrer")

    def _require_header(self, key: str, expected: str) -> None:
        if (self.header_policy or {}).get(key) != expected:
            raise HostingProfileError(
                f"static-encrypted requires headerPolicy.{key} = {expected!r}."
            )


@dataclass(frozen=True)
class StudentProjection:
    student_id: str
    view: dict
    projection_hash: str
    identity_projection_hash: Optional[str] = None


@dataclass
class PreparedRelease:
    release_id: str
    release_hash: str
    plan_dir: Path
    plan: dict
