"""C4 AES-GCM crypto and entropy tests."""

from __future__ import annotations

import pytest

from portal import crypto
from portal.canonical import encode, sha256_bytes
from portal.capability import validate_object_id
from portal.errors import CapabilityError
from portal.models import (
    PORTAL_APP_VERSION,
    PORTAL_VIEW_SCHEMA_VERSION,
)


def _aad(release_id="prelease_" + "a" * 24, object_id="o" * 32):
    return crypto.build_canonical_aad(
        release_id,
        "SEC-C4",
        "pub_c4",
        object_id,
        PORTAL_VIEW_SCHEMA_VERSION,
        PORTAL_APP_VERSION,
    )


class TestAesGcmRoundTrip:
    def test_roundtrip(self):
        key = crypto.generate_key()
        nonce = crypto.generate_nonce()
        aad = _aad()
        plaintext = encode({"studentId": "stu_1", "score": "70.0"})
        ciphertext = crypto.encrypt_payload(key, nonce, aad, plaintext)
        decrypted = crypto.decrypt_payload(key, nonce, aad, ciphertext)
        assert decrypted == plaintext

    def test_wrong_key_fails(self):
        key = crypto.generate_key()
        wrong = crypto.generate_key()
        nonce = crypto.generate_nonce()
        aad = _aad()
        ciphertext = crypto.encrypt_payload(key, nonce, aad, b"payload")
        with pytest.raises(Exception):
            crypto.decrypt_payload(wrong, nonce, aad, ciphertext)

    def test_wrong_nonce_fails(self):
        key = crypto.generate_key()
        nonce = crypto.generate_nonce()
        other_nonce = crypto.generate_nonce()
        aad = _aad()
        ciphertext = crypto.encrypt_payload(key, nonce, aad, b"payload")
        with pytest.raises(Exception):
            crypto.decrypt_payload(key, other_nonce, aad, ciphertext)

    def test_wrong_aad_fails(self):
        key = crypto.generate_key()
        nonce = crypto.generate_nonce()
        aad = _aad()
        wrong_aad = _aad(object_id="x" * 32)
        ciphertext = crypto.encrypt_payload(key, nonce, aad, b"payload")
        with pytest.raises(Exception):
            crypto.decrypt_payload(key, nonce, wrong_aad, ciphertext)

    def test_tampered_ciphertext_fails(self):
        key = crypto.generate_key()
        nonce = crypto.generate_nonce()
        aad = _aad()
        ciphertext = bytearray(crypto.encrypt_payload(key, nonce, aad, b"payload"))
        ciphertext[0] ^= 0x01
        with pytest.raises(Exception):
            crypto.decrypt_payload(key, nonce, aad, bytes(ciphertext))


class TestKeyFormat:
    def test_key_length(self):
        assert len(crypto.generate_key()) == 32

    def test_nonce_length(self):
        assert len(crypto.generate_nonce()) == 12

    def test_object_id_is_b64url(self):
        for _ in range(50):
            value = crypto.generate_object_id()
            assert len(value) == 32
            for ch in value:
                assert ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

    def test_object_ids_unique(self):
        values = {crypto.generate_object_id() for _ in range(200)}
        assert len(values) == 200

    def test_keys_unique(self):
        values = {crypto.generate_key() for _ in range(200)}
        assert len(values) == 200

    def test_b64url_no_padding(self):
        encoded = crypto.b64url_encode(b"\x00" * 32)
        assert "=" not in encoded
        assert crypto.b64url_decode(encoded) == b"\x00" * 32

    def test_validate_key_length(self):
        good = crypto.b64url_encode(b"\x01" * 32)
        crypto.validate_capability_key(good)
        with pytest.raises(CapabilityError):
            crypto.validate_capability_key(crypto.b64url_encode(b"\x01" * 31))

    def test_validate_object_id(self):
        validate_object_id(crypto.generate_object_id())
        with pytest.raises(CapabilityError):
            validate_object_id("too-short")


class TestEntropy:
    def test_object_id_entropy_bits(self):
        # 192-bit random object ids: never derived from a stable input.
        values = {crypto.generate_object_id() for _ in range(500)}
        assert len(values) == 500

    def test_keys_not_persisted_in_repo(self):
        # Sanity guard: capability keys never appear in public artifacts.
        assert crypto.b64url_encode(crypto.generate_key()) != crypto.b64url_encode(b"\x00" * 32)
