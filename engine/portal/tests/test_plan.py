"""C4 release intent hash tests."""

from __future__ import annotations

from portal.models import PORTAL_APP_VERSION
from portal.plan import (
    compute_release_intent_hash,
    release_id_from_intent,
)
from portal.models import HostingProfile


def _profile():
    return HostingProfile(
        profile_id="local-static-v1",
        mode="static-encrypted",
        base_url="https://portal.example.test/",
        tls_required=True,
        directory_listing_disabled=True,
        header_policy={"contentSecurityPolicy": "default-src 'none';",
                       "referrerPolicy": "no-referrer",
                       "xContentTypeOptions": "nosniff",
                       "noindex": True},
        cache_policy={"mode": "no-store"},
        supports_atomic_promotion=True,
        supports_delete=True,
        supports_purge=True,
    )


def _intent():
    p = _profile()
    return compute_release_intent_hash(
        "SEC-C4",
        "pub_c4",
        "c" * 64,
        "r" * 64,
        "legacy-effective",
        PORTAL_APP_VERSION,
        p.profile_hash,
        "static-encrypted",
    )


class TestReleaseIntent:
    def test_deterministic(self):
        assert _intent() == _intent()

    def test_changes_with_snapshot_hash(self):
        a = _intent()
        b = compute_release_intent_hash(
            "SEC-C4", "pub_c4", "d" * 64, "r" * 64, "legacy-effective",
            PORTAL_APP_VERSION, _profile().profile_hash, "static-encrypted",
        )
        assert a != b

    def test_changes_with_profile(self):
        p1 = _profile()
        p2 = _profile()
        object.__setattr__(p2, "profile_id", "other-profile")
        a = compute_release_intent_hash(
            "SEC-C4", "pub_c4", "c" * 64, "r" * 64, "legacy-effective",
            PORTAL_APP_VERSION, p1.profile_hash, "static-encrypted",
        )
        b = compute_release_intent_hash(
            "SEC-C4", "pub_c4", "c" * 64, "r" * 64, "legacy-effective",
            PORTAL_APP_VERSION, p2.profile_hash, "static-encrypted",
        )
        assert a != b

    def test_changes_with_mode(self):
        a = _intent()
        b = compute_release_intent_hash(
            "SEC-C4", "pub_c4", "c" * 64, "r" * 64, "legacy-effective",
            PORTAL_APP_VERSION, _profile().profile_hash, "authenticated",
        )
        assert a != b

    def test_release_id_shape(self):
        release_id = release_id_from_intent(_intent())
        assert release_id.startswith("prelease_")
        assert len(release_id) == 9 + 24

    def test_release_id_is_stable_intent(self):
        # Same intent => same release id; a different intent => different id.
        assert release_id_from_intent(_intent()) == release_id_from_intent(_intent())
        other = compute_release_intent_hash(
            "SEC-C4", "pub_other", "c" * 64, "r" * 64, "legacy-effective",
            PORTAL_APP_VERSION, _profile().profile_hash, "static-encrypted",
        )
        assert release_id_from_intent(_intent()) != release_id_from_intent(other)
