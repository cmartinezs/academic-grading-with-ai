"""Generate a real Python-encrypted payload for the Node interop test.

Writes interop.json consumed by app.interop.test.js. The Node app must decrypt
this ciphertext with WebCrypto AES-GCM using the same canonical AAD built from
the same components (base64url without padding, 96-bit nonce, 256-bit key).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def main(out_path: Path) -> None:
    from portal.canonical import encode
    from portal.crypto import (
        b64url_encode,
        build_canonical_aad,
        encrypt_payload,
        generate_key,
        generate_nonce,
    )

    release_id = "prelease_" + "ab" * 12
    section_id = "SEC-C4"
    publication_id = "pub_interop"
    object_id = "".join(chr(ord("a") + i % 26) for i in range(32))
    schema_version = "1.0.0"
    app_version = "0.1.0"

    view = {
        "schemaVersion": "1.0.0",
        "studentId": "interop-student",
        "displayName": "Interop",
        "assessments": [
            {
                "assessmentId": "ev1",
                "label": "EV1 - P1",
                "status": "Evaluada",
                "score": 70.0,
                "grade": 5.5,
                "feedback": "Buen trabajo",
            }
        ],
        "finalOutcome": {"value": 5.5, "unit": "nota"},
    }
    key = generate_key()
    nonce = generate_nonce()
    aad = build_canonical_aad(
        release_id, section_id, publication_id, object_id, schema_version, app_version
    )
    ciphertext = encrypt_payload(key, nonce, aad, encode(view))

    out_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "releaseId": release_id,
                "sectionId": section_id,
                "publicationId": publication_id,
                "objectId": object_id,
                "portalViewSchemaVersion": schema_version,
                "portalAppVersion": app_version,
                "aadB64": b64url_encode(aad),
                "nonceB64": b64url_encode(nonce),
                "keyB64": b64url_encode(key),
                "ciphertextB64": b64url_encode(ciphertext),
                "expectedView": view,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
