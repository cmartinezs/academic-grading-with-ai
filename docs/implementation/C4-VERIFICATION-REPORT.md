# C4 Verification Report

## Status: COMPLETE

## Verified head

- Branch: `feat/c4-secure-portal`
- Base: `master` (contiene C3 merge `538c2b425b6e28be59198698d8d1d8cac55717a5`)
- Pull request: Draft
- Remote CI: pendiente de la carrera del Draft PR (c4.yml incluye gates C0–C4)

## Contracts verified

| Contract | Status | Details |
|---|---|---|
| StudentPortalView V1 | Pass | Proyección determinista por estudiante, legacy-effective y grade-policy-effective, sin PII adicional en la vista pública cifrada |
| PortalReleasePlan V1 | Pass | Snapshot anidado (contentHash/reviewHash/mode), hostingProfile, `additionalProperties:false` |
| PortalHostingProfile V1 | Pass | static-encrypted y authenticated (subject-bound), preflight fail-closed |
| PortalApproval V1 | Pass | Bind a releaseHash e identityProjectionHash; drift bloquea publish |
| Receipts V1 | Pass | publish incluye releaseHash/hostingProfileId/publisherType/objectCount; revoke/purge no; `required` condicional por tipo |
| Capability Manifest V1 | Pass | `key` solo en entries privadas; la vista pública no lleva capabilityKey |
| Public Bundle Manifest V1 | Pass | Solo objectId/artifactHash/metadataHash/ciphertextSha256 |

## Source snapshot authority

Todo prepare/approve/publish verifica el snapshot inmutable con el verificador
canónico C1:

```python
publication.verify.verify_snapshot(
    snapshot_dir,
    section_id=section_id,
    publication_id=publication_id,
    immutable=True,
)
```

- `manifest.status == "approved"` y estado de lifecycle exactamente `approved`.
- `revoked`/`corrected`/`superseded` son terminales y bloquean prepare/approve/publish.
- `snapshotMode` se deriva de `canonical/policy.json`, nunca se adivina.
- Tampering tras prepare bloquea approve; tampering tras approve bloquea publish.

## Hashing

| Hash | Algoritmo | Verificado |
|---|---|---|
| projectionHash | SHA-256(canonical JSON de la proyección) | Yes |
| releaseIntentHash | SHA-256(sectionId+publicationId+snapshotContentHash+snapshotReviewHash+snapshotMode+portalAppVersion+hostingProfileHash+portalMode) | Yes |
| releaseId | `prelease_` + releaseIntentHash[:24] | Yes |
| releaseHash | SHA-256(payload completo con snapshot, hostingProfile, objects, capabilityManifestHash, publicBundleManifestHash) | Yes |
| idempotencyKey | SHA-256(releaseId+releaseHash+hostingProfileId+publisherType) | Yes |
| identityProjectionHash | SHA-256(studentId+displayName+contactEmail), misma convención que C3 | Yes |

El releaseHash es determinista entre `prepare_release` repetidas sobre la misma
proyección (re-uso del plan, sin reintentar encrypt).

## Criptografía

| Propiedad | Resultado |
|---|---|
| Algoritmo | AES-256-GCM (solo `cryptography.hazmat.primitives.ciphers.aead.AESGCM`) |
| Claves | 256 bits, una por estudiante, nunca reutilizadas, nunca en repositorio/ledger/receipts |
| Nonces | 96 bits, únicos por key |
| Object IDs | 192 bits (`token_bytes(24)`), base64url sin padding, no derivados de studentId |
| AAD canónico | Base64url sin padding; el browser reconstruye los mismos bytes |
| Capability URL | `https://host/<publicationId>/<objectId>/#k=<base64url>` (fragment, nunca query) |
| Interop Node ↔ Python | El browser (WebCrypto) descifra un ciphertext Python real |

## State machine

```
prepared → approved → publishing → published → revoked → purged
                 \                     \--> blocked (reconciliación)
                  \--> blocked
```

| Transición | Verificado |
|---|---|
| prepared → approved | Yes |
| approved → publishing | Yes |
| publishing → published | Yes |
| publishing → partial | Yes (fail_publish) |
| partial → publishing → published | Yes (reconcile) |
| partial/publishing → blocked | Yes (reconcile incompleto) |
| published → revoked | Yes |
| revoked → purged | Yes |
| published → published (idempotente, mismo releaseHash) | Yes |

## Concurrencia e idempotencia

- Dos `prepare` concurrentes producen el mismo plan (mismo releaseId y releaseHash).
- Dos `publish` concurrentes: un ganador, at-most-once; el perdedor espera y
  devuelve el mismo receipt (UNIQUE en `publish_runs.idempotencyKey`).
- `record_release` idempotente bajo carrera (IntegrityError → no-op).

## Failure injection

| Escenario | Resultado | Verificado |
|---|---|---|
| Publish falla a mitad | `partial` | Yes |
| Reconcile con deployment completo | promueve a `published` con receipt | Yes |
| Reconcile sin deployment | `blocked` | Yes |
| Deployment pierde un objeto | drift detectado (`missingObjects`) | Yes |
| Identity drift tras approve | publish bloqueado (`IdentityDriftError`) | Yes |
| Snapshot tamper tras approve | publish bloqueado, cero despliegues | Yes |
| Plan tamper | publish/verify bloqueados | Yes |

## Privacidad

- La vista pública cifrada no contiene PII legible (no rut/email/nota en claro).
- Capability keys nunca en: public bundle, ledger SQLite, receipts, logs o deployment.
- Receipts solo contienen hashes, ids y conteos.
- Permisos: plans 0700/0600, ledger 0600, receipts 0700/0600.
- Scanner estricto C0: BLOCK=0, REVIEW=0 (con allowlist de fixtures sintéticos).

## Tests

| Suite | Resultado |
|---|---:|
| C4 pytest (models, crypto, capability, plan, schemas, projection, bundle, ledger, lifecycle, privacy, hosting, concurrency, reconciliation) | 125 passed |
| C4 Node WebCrypto ↔ Python AES-GCM interop | 5 passed |
| C4 CLI E2E sintético (prepare→approve→publish→verify→status→revoke→purge) | OK |
| C3 regression | 199 passed |
| C2 regression | incluida en engine (grade-policy tests) |
| C1 regression | incluida en engine (publication tests) |
| C0 regression | 92+ passed |
| Engine completo | 735 passed, 1 skipped |
| Scanner estricto | 282 files, BLOCK=0, REVIEW=0 |

## Exit codes CLI

| Código | Significado | Verificado |
|---|---|---|
| 0 | éxito / completo | Yes |
| 1 | uso/configuración (falta `--confirm-*`) | Yes |
| 2 | validación/seguridad/gate de aprobación | Yes |
| 3 | parcial/blocked/operacional | Yes |

No existen `--force`, `--auto-approve`, `--plaintext` ni `--short-code`.

## Out of scope

- C5 teacher/3FN/BI
- C6 conventions
- C7 discovery
- Integración real con Firebase/Supabase/Cloudflare o proveedor SaaS (el modo
  `authenticated` usa un reference adapter `fake_authenticated`)
- Analytics, pixels, scripts externos, fonts remotas, service workers en V1
- Distribución automática de capabilities por email
