"""C4 capability URL and object-id tests."""

from __future__ import annotations

import pytest

from portal.capability import (
    build_capability_url,
    generate_subject_ref,
    validate_object_id,
)
from portal.crypto import b64url_encode, generate_object_id
from portal.errors import CapabilityError


class TestCapabilityUrl:
    def test_url_shape(self):
        key = b64url_encode(b"\x05" * 32)
        url = build_capability_url(
            "https://portal.example.test/", "pub_c4", "objectid1234567890abcdefghij", key
        )
        assert url == (
            "https://portal.example.test/pub_c4/objectid1234567890abcdefghij/#k=" + key
        )

    def test_key_only_in_fragment(self):
        key = b64url_encode(b"\x05" * 32)
        url = build_capability_url("https://h/", "pub", "o" * 32, key)
        assert "?" not in url
        assert url.split("#", 1)[1].startswith("k=")

    def test_subject_ref_is_opaque(self):
        refs = {generate_subject_ref() for _ in range(50)}
        assert len(refs) == 50


class TestObjectId:
    def test_validation_rejects_bad_chars(self):
        with pytest.raises(CapabilityError):
            validate_object_id("!" * 32)

    def test_validation_rejects_wrong_length(self):
        with pytest.raises(CapabilityError):
            validate_object_id(generate_object_id()[:-1])
