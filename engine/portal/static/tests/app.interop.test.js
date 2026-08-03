/* C4 static app unit tests: pure helpers plus WebCrypto interop with the
 * ciphertext produced by the Python portal module (portal.crypto AES-256-GCM).
 * Run: node --test tests/app.interop.test.js
 */
"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const app = require("../app.js");

function b64urlToBytes(text) {
  const b64 = String(text).replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
  const bin = atob(b64 + pad);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

test("b64urlToBytes / bytesToB64url roundtrip is unpadded", () => {
  const raw = crypto.getRandomValues(new Uint8Array(32));
  const encoded = app.bytesToB64url(raw);
  assert.ok(!encoded.includes("="), "output must be unpadded base64url");
  assert.deepStrictEqual(app.b64urlToBytes(encoded), raw);
});

test("parseKeyFromHash requires a # fragment with a 32-byte key", () => {
  const key = crypto.getRandomValues(new Uint8Array(32));
  const b64 = app.bytesToB64url(key);
  assert.deepStrictEqual(app.parseKeyFromHash("#k=" + b64), key);
  assert.strictEqual(app.parseKeyFromHash(""), null);
  assert.strictEqual(app.parseKeyFromHash("#"), null);
  assert.strictEqual(app.parseKeyFromHash("#other=1"), null);
  const short = app.bytesToB64url(crypto.getRandomValues(new Uint8Array(16)));
  assert.strictEqual(app.parseKeyFromHash("#k=" + short), null);
});

test("validateView accepts a valid view and rejects bad ones", () => {
  const view = {
    schemaVersion: "1.0.0",
    studentId: "s1",
    assessments: [],
  };
  assert.strictEqual(app.validateView(view), view);
  assert.throws(() => app.validateView(null), /invalid-view/);
  assert.throws(() => app.validateView({}), /unsupported-view-schema/);
  assert.throws(
    () => app.validateView({ schemaVersion: "1.0.0", assessments: [] }),
    /invalid-student/
  );
});

test("Node WebCrypto decrypts the Python-encrypted interop payload", () => {
  const here = __dirname;
  const root = path.resolve(here, "..", "..", "..", "..");
  const fixture = path.join(here, "interop.json");
  const py = process.env.PYTHON_BIN || "python3";
  execFileSync(
    py,
    [path.join(here, "make_interop_fixture.py"), fixture],
    { cwd: root }
  );
  const data = JSON.parse(fs.readFileSync(fixture, "utf-8"));

  const key = b64urlToBytes(data.keyB64);
  const nonce = b64urlToBytes(data.nonceB64);
  const aad = b64urlToBytes(data.aadB64);
  const ciphertext = b64urlToBytes(data.ciphertextB64);

  return app
    .decryptPayload(key, nonce, aad, ciphertext)
    .then((plaintext) => {
      const view = app.validateView(
        JSON.parse(new TextDecoder().decode(plaintext))
      );
      assert.strictEqual(view.studentId, data.expectedView.studentId);
      assert.strictEqual(view.assessments.length, 1);
      assert.strictEqual(view.assessments[0].grade, 5.5);
      assert.strictEqual(view.finalOutcome.value, 5.5);
    });
});

test("b64urlToBytes rejects invalid base64url input", () => {
  const key = crypto.getRandomValues(new Uint8Array(32));
  const b64 = app.bytesToB64url(key);
  assert.throws(() => app.b64urlToBytes(b64 + "!")); // non-alphabet character
});
