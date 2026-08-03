/* C4 static portal app.
 *
 * Loads the capability key from location.hash (#k=...), clears the fragment,
 * loads metadata.json + payload.enc, reconstructs/uses the canonical AAD from
 * metadata, decrypts with Web Crypto AES-GCM, validates the StudentPortalView,
 * and renders with textContent. No remote scripts, no innerHTML for academic
 * content, no localStorage/sessionStorage for the key, no extra requests.
 */
(() => {
  "use strict";

  /* ---------- pure helpers (exported for Node tests) ---------- */

  function b64urlToBytes(text) {
    const b64 = String(text).replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
    const bin = atob(b64 + pad);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  function bytesToB64url(bytes) {
    let bin = "";
    for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function parseKeyFromHash(hash) {
    if (!hash || hash[0] !== "#") return null;
    const params = new URLSearchParams(hash.slice(1));
    const k = params.get("k");
    if (!k) return null;
    const bytes = b64urlToBytes(k);
    if (bytes.length !== 32) return null; // AES-256 requires 32 bytes
    return bytes;
  }

  function clearHashFromUrl() {
    history.replaceState(null, "", location.pathname + location.search);
  }

  async function importAesKey(bytes) {
    return crypto.subtle.importKey(
      "raw",
      bytes,
      { name: "AES-GCM" },
      false,
      ["decrypt"]
    );
  }

  async function decryptPayload(keyBytes, nonceBytes, aadBytes, ciphertextBytes) {
    const key = await importAesKey(keyBytes);
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: nonceBytes, additionalData: aadBytes },
      key,
      ciphertextBytes
    );
    return new Uint8Array(plaintext);
  }

  function validateView(view) {
    if (!view || typeof view !== "object") throw new Error("invalid-view");
    if (view.schemaVersion !== "1.0.0") throw new Error("unsupported-view-schema");
    if (!Array.isArray(view.assessments)) throw new Error("invalid-assessments");
    if (typeof view.studentId !== "string" || !view.studentId) {
      throw new Error("invalid-student");
    }
    return view;
  }

  /* ---------- rendering ---------- */

  function renderView(view, contentEl) {
    const heading = document.createElement("h2");
    heading.textContent = "Mis resultados";
    contentEl.appendChild(heading);

    if (view.finalOutcome && view.finalOutcome.value) {
      const finalEl = document.createElement("p");
      finalEl.textContent = `Nota final: ${view.finalOutcome.value} ${view.finalOutcome.unit || ""}`;
      contentEl.appendChild(finalEl);
    }

    const list = document.createElement("dl");
    for (const item of view.assessments) {
      const term = document.createElement("dt");
      term.textContent = item.label || item.assessmentId || "Evaluación";
      list.appendChild(term);

      const detail = document.createElement("dd");
      const parts = [];
      if (item.status) parts.push(item.status);
      if (item.score !== null && item.score !== undefined) parts.push(`Puntaje: ${item.score}`);
      if (item.grade !== null && item.grade !== undefined) parts.push(`Nota: ${item.grade}`);
      detail.textContent = parts.join(" · ");
      list.appendChild(detail);

      if (item.feedback) {
        const feedbackEl = document.createElement("dd");
        feedbackEl.textContent = item.feedback;
        list.appendChild(feedbackEl);
      }
    }
    contentEl.appendChild(list);
  }

  function showError(contentEl) {
    const msg = document.createElement("p");
    msg.textContent = "No se pudo abrir la vista. Verifica el enlace recibido.";
    contentEl.appendChild(msg);
  }

  /* ---------- boot (browser only) ---------- */

  async function boot() {
    const contentEl = document.getElementById("view");
    if (!contentEl) return;
    let keyBytes;
    try {
      keyBytes = parseKeyFromHash(location.hash);
    } catch (err) {
      keyBytes = null;
    }
    if (!keyBytes) {
      showError(contentEl);
      return;
    }
    try {
      clearHashFromUrl();
    } catch (err) {
      /* noop */
    }
    try {
      const metadataResp = await fetch("metadata.json", { cache: "no-store" });
      const payloadResp = await fetch("payload.enc", { cache: "no-store" });
      if (!metadataResp.ok || !payloadResp.ok) throw new Error("fetch-failed");
      const metadata = await metadataResp.json();
      const ciphertext = new Uint8Array(await payloadResp.arrayBuffer());
      if (metadata.schemaVersion !== "1.0.0") throw new Error("unsupported-metadata");
      const nonceBytes = b64urlToBytes(metadata.nonce);
      const aadBytes = b64urlToBytes(metadata.aad);
      const plaintext = await decryptPayload(keyBytes, nonceBytes, aadBytes, ciphertext);
      const view = validateView(JSON.parse(new TextDecoder().decode(plaintext)));
      renderView(view, contentEl);
    } catch (err) {
      showError(contentEl);
    }
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }

  const api = {
    b64urlToBytes,
    bytesToB64url,
    parseKeyFromHash,
    decryptPayload,
    validateView,
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.portalApp = api;
  }
})();
