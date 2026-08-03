# C4 Implementation Plan — Secure Student Portal

Estado: IMPLEMENTADO (verificación en `C4-VERIFICATION-REPORT.md`). Rama: `feat/c4-secure-portal`.
Base: `master` (contiene C3 merge `538c2b425b6e28be59198698d8d1d8cac55717a5`).

Este corte implementa exclusivamente C4 del roadmap
[`04-roadmap.md`](../architecture/04-roadmap.md). C5–C7 quedan fuera de alcance.

## 1. Estado actual verificado (baseline)

| Gate | Resultado |
|---|---|
| `./scripts/email-delivery.sh test` | 199 passed |
| `./scripts/grade-policy.sh test` | OK + E2E OK |
| `./scripts/publication-snapshot.sh test` | 121 tests OK (1 skipped) + E2E OK |
| `./scripts/c0-test.sh` | 92 tests OK |
| `./scripts/c0-scan.sh --tracked --strict` | 278 files · BLOCK=0 · REVIEW=0 |
| `git diff --check` | OK |

SHA de base: `538c2b425b6e28be59198698d8d1d8cac55717a5` (merge C3).
HEAD de trabajo tras la limpieza de `.opencode/`: `c9c1cc2`, luego commit documental
`6ec9be9` (C3 as merged and verified).

## 2. Contratos C1–C3 que no pueden romperse

1. `publication.verify.verify_snapshot(..., immutable=True)` es la autoridad para
   verificar el Publication Snapshot aprobado e inmutable (C1).
2. El snapshotMode se deriva de `canonical/policy.json` (`legacy-effective` para C1,
   `grade-policy-effective` para C2), nunca se adivina.
3. `canonical/results.json` conserva los resultados observados; `canonical/outcomes.json`
   conserva los outcomes calculados por grade-policy (C2).
4. El lifecycle del snapshot se lee del ledger append-only C1
   (`publication.lifecycle.LifecycleLedger`). `revoked`/`corrected`/`superseded` son
   terminales y bloquean prepare/approve/publish.
5. `identityProjectionHash` reutiliza la misma convención que C3
   (`email_delivery.canonical.compute_identity_projection_hash`) para detectar drift.
6. C0–C3 permanecen verdes; el scanner estricto queda `BLOCK=0 REVIEW=0`.

## 3. Perfil soportado C4 V1

### A. Modo `static-encrypted` (operativo completo)

- Una proyección cifrada por estudiante.
- AES-256-GCM (solo `cryptography.hazmat.primitives.ciphers.aead.AESGCM`).
- Capability de alta entropía (clave 256 bits) en URL fragment.
- Object IDs no enumerables (≥192 bits, aleatorios, no derivados).
- Aplicación estática sin dependencias remotas.
- Publicación, revoke y purge con receipts durables.
- Publisher local probado de extremo a extremo.

### B. Modo `authenticated` (contrato + reference adapter)

- Contrato cerrado de adapter.
- Hosting profile con `authorizationModel: subject-bound`.
- Reference/fake authenticated publisher.
- Autorización subject-bound y pruebas de aislamiento entre estudiantes.
- Preflight fail-closed.

### Límite explícito del modo authenticated en C4 V1

No se implementa integración real con Firebase, Supabase, Cloudflare ni ningún
proveedor SaaS. El adapter `fake_authenticated` es un reference/reference adapter para
probar el contrato; **no** es un hosting productivo externo. Esta ausencia se documenta
como límite del modo, no se oculta.

## 4. Contratos del módulo

- `StudentPortalView V1` — véase `C4-PORTAL-CONTRACT.md` §2.
- `PortalReleasePlan V1` — véase `C4-PORTAL-CONTRACT.md` §3.
- `PortalHostingProfile V1` — véase `C4-PORTAL-CONTRACT.md` §4.
- `PortalApproval V1` — véase `C4-PORTAL-CONTRACT.md` §5.
- Receipts (publish/revoke/purge) — véase `C4-PORTAL-CONTRACT.md` §6.
- Hashing — véase `C4-PORTAL-CONTRACT.md` §7.
- State machine — véase `C4-STATE-MACHINE.md`.
- Threat model y decisiones criptográficas — véase `C4-SECURITY-MODEL.md`.

## 5. Storage

| Artefacto | Root | Clasificación | Permisos | Retención |
|---|---|---|---|---|
| Plan bundle (plan.json, manifest, capability-manifest, projections, public-bundle) | `private_root/portal/plans/<sectionId>/<publicationId>/<releaseId>/` | PII/privado | 0700 dir / 0600 file | Mientras exista el release |
| Plan staging | `private_root/portal/plans/.../.staging/` | Ephemeral privado | 0700 dir / 0600 file | Hasta promoción/descarte |
| Portal ledger | `state_root/portal/portal-ledger.sqlite3` | Estado operacional | 0600 | Indefinida (backup API) |
| Receipts | `state_root/portal/receipts/` | Estado operacional | 0700 dir / 0600 file | Indefinida |
| Recovery markers | `state_root/portal/recovery/` | Estado operacional | 0700 dir / 0600 file | Hasta resolución |
| Backups | `state_root/portal/backups/` | Estado operacional | 0700 | Por política |
| Deployments | `state_root/portal/deployments/` | Estado operacional | 0700 dir; 0644 solo archivos públicos cifrados dentro del deployment | Por política |
| Capabilities | `private_root/portal/plans/.../<releaseId>/capability-manifest.json` | Secreto | 0600 | Misma que el plan |
| Static app y schemas | Repositorio (`engine/portal/`) | Pública | Versionado | Permanente |

**Nunca se almacena** capability key en: repositorio, `publications_root`, logs,
artefactos de CI, deployment público, SQLite o receipts.

## 6. Hashes

```
releaseIntentHash = SHA-256(
    sectionId + publicationId + snapshotContentHash + snapshotReviewHash
    + snapshotMode + portalAppVersion + hostingProfileHash + portalMode)
releaseId = "prelease_" + releaseIntentHash[:24]
```

- `projectionHash`: SHA-256(canonical JSON de la proyección por estudiante).
- `artifactHash`: SHA-256 de cada artifact público.
- `capabilityManifestHash`: SHA-256 del capability manifest privado (sin la key).
- `releaseHash`: cubre snapshot hashes, portal mode, hosting profile, portal app version,
  cada projectionHash, cada objectId, cada ciphertext hash, cada metadata hash,
  capabilityManifestHash, manifest del public bundle y object count.
- Cambiar cualquier dato, objeto, key binding o artifact cambia `releaseHash`.

## 7. Object IDs y capabilities

- Object ID: `secrets.token_bytes(24)` (192 bits), base64url sin padding, no secuencial,
  no derivado de `studentId`, no reutilizado dentro de un release.
- Capability key: 256 bits aleatorios, base64url sin padding, una distinta por
  estudiante, no reutilizada entre publications, nunca en metadata pública, ledger o
  receipts.
- Nonce: 96 bits aleatorios por cifrado, único por key.
- Capability URL: `https://host/<publicationId>/<objectId>/#k=<base64url-key>`.
- Prohibido: clave o token transportado como parámetro de query string, `/key/` en
  path, PIN, RUT, fechas, hashes simples de studentId.

## 8. Lifecycle de release

```
prepared → approved → publishing → published → revoked → purged
                 \                            \--> blocked (durante reconciliación)
                  \--> blocked
```

Véase `C4-STATE-MACHINE.md` para transiciones exactas.

## 9. Tasks incrementales

1. `engine/portal/` base (errors, models, canonical JSON, clock).
2. Schemas JSON versionados + validators (`schemas/`).
3. Proyección estudiante determinista (`projection.py`).
4. Cifrado AES-GCM (`crypto.py`) y capabilities (`capability.py`).
5. Release intent / hashes / bundle (`bundle.py`, `snapshot.py`, `plan.py`).
6. Aprobación ligada a releaseHash (`approval.py`).
7. Ledger SQLite durable y receipts (`ledger.py`, `receipts.py`).
8. Publisher local estático y publisher authenticated fake (`hosting/`).
9. Lifecycle, revoke/purge y reconciliación (`lifecycle.py`, `reconciliation.py`).
10. Aplicación estática (`static/`) y tests de la app.
11. CLI `engine/scripts/portal.py` + wrapper `scripts/portal.sh`.
12. Tests (unit, integración, concurrencia, failure injection, privacidad, entropía).
13. Interop WebCrypto Node ↔ Python AESGCM.
14. CI `c4.yml`.
15. Docs (plan, contrato, security model, state machine, runbooks, verificación) +
    actualización de índices.

## 10. Exit codes CLI

- `0` éxito / completo.
- `1` uso/configuración.
- `2` validación/seguridad/gate de aprobación (fail-closed).
- `3` parcial/blocked/estado operacional.

Confirmaciones obligatorias (el dominio también rechaza `False`):

- `--confirm-reviewed`
- `--confirm-publish`
- `--confirm-revoke`
- `--confirm-purge`

No existe: `--force`, `--auto-approve`, `--plaintext`, `--short-code`.

## 11. Dependencias

- `cryptography` (solo `AESGCM` para AES-256-GCM).
- `jsonschema` (ya pinneada por C1/C3).
- Versiones revisadas y reproducibles en `engine/portal/requirements.txt`.
- Ausencia de `cryptography` o `jsonschema` bloquea (fail-closed).
- No se implementa criptografía propia.

## 12. Crash/Recovery model

| Punto de crash | Estado | Recuperación |
|---|---|---|
| Antes del rename del plan | staging recuperable | re-prepare idempotente |
| Después del rename del plan | plan completo | approve o discard |
| Después de approval, antes de publish | aprobado | publish (idempotente) |
| A mitad del deployment | `partial` | reconcile → publish o discard |
| Después del deployment, antes del receipt | deployment existe sin receipt | reconcile → receipt |
| Después del receipt | `published` | terminal para ese releaseHash |

## 13. Failure model

| Fallo | Resultado | Recuperación |
|---|---|---|
| Snapshot no aprobado o terminal | prepare/approve/publish rechazados | corregir snapshot |
| Snapshot tampered tras prepare | approval rechazado | nuevo prepare |
| Snapshot tampered tras approval | publish rechazado | nuevo release |
| Plan tampered | publish rechazado | nuevo prepare |
| Capability manifest tampered | verify/approve/publish rechazados | nuevo prepare |
| Identity drift | publish rechazado | resolver IdentityStore |
| Hosting preflight falla | publish rechazado | corregir hosting |
| Disk full / state_root / private_root | release no parcial | reintentar |
| Concurrencia publish | un ganador, at-most-once | ledger UNIQUE |

## 14. Compatibilidad

C4 verifica C1, C2 y C3 regresiones completas y mantiene el scanner estricto limpio.
No modifica los contracts de C1–C3.

## 15. Fuera de alcance

- C5 proyecciones teacher/3FN/BI.
- C6 convenciones.
- C7 discovery.
- Integración real Firebase/Supabase/Cloudflare o cualquier proveedor SaaS.
- Analytics, pixels, scripts externos, fonts remotas, service workers en V1.
- Distribución automática de capabilities por email (C3 puede entregarlas, pero el
  portal no depende del email).
