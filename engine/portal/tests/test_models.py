"""C4 domain model and validator tests."""

from __future__ import annotations

import pytest

from portal.errors import HostingProfileError
from portal.models import (
    HostingProfile,
    validate_actor,
    validate_publication_id,
    validate_release_id,
    validate_section_id,
)


def _profile(**overrides):
    data = {
        "profile_id": "p1",
        "mode": "static-encrypted",
        "base_url": "https://portal.example.test/",
        "tls_required": True,
        "directory_listing_disabled": True,
        "header_policy": {
            "contentSecurityPolicy": "default-src 'none';",
            "referrerPolicy": "no-referrer",
            "xContentTypeOptions": "nosniff",
            "noindex": True,
        },
        "cache_policy": {"mode": "no-store"},
        "supports_atomic_promotion": True,
        "supports_delete": True,
        "supports_purge": True,
        "authorization_model": None,
    }
    data.update(overrides)
    return HostingProfile(**data)


class TestIdValidators:
    def test_section_id_valid(self):
        assert validate_section_id("CUR0001-001") == "CUR0001-001"

    def test_section_id_rejects_empty(self):
        with pytest.raises(HostingProfileError):
            validate_section_id("")

    def test_publication_id_prefix(self):
        assert validate_publication_id("pub_abc123") == "pub_abc123"

    def test_publication_id_rejects_plain(self):
        with pytest.raises(HostingProfileError):
            validate_publication_id("abc")

    def test_release_id_prefix(self):
        assert validate_release_id("prelease_" + "a" * 24) == "prelease_" + "a" * 24

    def test_release_id_rejects_bad(self):
        with pytest.raises(HostingProfileError):
            validate_release_id("eplan_abc")

    def test_actor_rejects_email(self):
        with pytest.raises(HostingProfileError):
            validate_actor("user@example.com")

    def test_actor_rejects_empty(self):
        with pytest.raises(HostingProfileError):
            validate_actor("")

    def test_actor_accepts_opaque(self):
        assert validate_actor("user.approver-1") == "user.approver-1"


class TestStaticEncryptedProfile:
    def test_valid_static_profile_passes(self):
        _profile().validate_mode_requirements()

    def test_tls_required(self):
        with pytest.raises(HostingProfileError):
            _profile(tls_required=False).validate_mode_requirements()

    def test_directory_listing_must_be_disabled(self):
        with pytest.raises(HostingProfileError):
            _profile(directory_listing_disabled=False).validate_mode_requirements()

    def test_csp_required(self):
        header_policy = {
            "referrerPolicy": "no-referrer",
            "xContentTypeOptions": "nosniff",
            "noindex": True,
        }
        with pytest.raises(HostingProfileError):
            _profile(header_policy=header_policy).validate_mode_requirements()

    def test_referrer_policy_required(self):
        header_policy = {
            "contentSecurityPolicy": "default-src 'none';",
            "xContentTypeOptions": "nosniff",
            "noindex": True,
        }
        with pytest.raises(HostingProfileError):
            _profile(header_policy=header_policy).validate_mode_requirements()

    def test_cache_policy_required(self):
        with pytest.raises(HostingProfileError):
            _profile(cache_policy={}).validate_mode_requirements()

    def test_static_forbids_authorization_model(self):
        with pytest.raises(HostingProfileError):
            _profile(authorization_model="subject-bound").validate_mode_requirements()


class TestAuthenticatedProfile:
    def test_valid_authenticated_profile_passes(self):
        _profile(
            mode="authenticated",
            authorization_model="subject-bound",
            cache_policy={"mode": "private-no-store"},
            header_policy={
                "referrerPolicy": "no-referrer",
                "crossStudentAccess": "denied",
                "contentSecurityPolicy": "default-src 'none';",
            },
        ).validate_mode_requirements()

    def test_requires_subject_bound(self):
        with pytest.raises(HostingProfileError):
            _profile(
                mode="authenticated",
                authorization_model=None,
                cache_policy={"mode": "private-no-store"},
            ).validate_mode_requirements()

    def test_requires_private_no_store(self):
        with pytest.raises(HostingProfileError):
            _profile(
                mode="authenticated",
                authorization_model="subject-bound",
                cache_policy={"mode": "public"},
            ).validate_mode_requirements()

    def test_requires_cross_student_denied(self):
        with pytest.raises(HostingProfileError):
            _profile(
                mode="authenticated",
                authorization_model="subject-bound",
                cache_policy={"mode": "private-no-store"},
                header_policy={"referrerPolicy": "no-referrer"},
            ).validate_mode_requirements()
