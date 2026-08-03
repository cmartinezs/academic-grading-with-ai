# C4 Portal Contract

Contratos exactos del portal de estudiantes. Los schemas JSON (Draft 2020-12) viven en
`engine/portal/schemas/`.

## 1. Versioning

Todo schema declara `schemaVersion`. Major desconocida → fail-closed; minor → aditivo.

## 2. StudentPortalView V1

Proyección individual mínima. Solo información del `studentId` correspondiente.

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "publicationId": "pub_...",
  "studentId": "stu_...",
  "snapshotMode": "legacy-effective",
  "assessments": [
    {
      "assessmentId": "EV01",
      "label": "Control 1",
      "status": "Evaluada",
      "score": "85.0",
      "grade": "6.4",
      "unit": "percent",
      "feedback": "texto opcional"
    }
  ],
  "finalOutcome": null,
  "generatedFrom": "student-portal/projection/v1"
}
```

### Campos mínimos

- `schemaVersion` (string)
- `sectionId` (string)
- `publicationId` (string)
- `studentId` (string opaco)
- `snapshotMode` (`"legacy-effective"` | `"grade-policy-effective"`)
- `assessments[]`
- `finalOutcome` (opcional)
- `generatedFrom` (string)

### Assessment

Cada assessment puede incluir únicamente:

- `assessmentId`
- `label`
- `status`
- `score` (Decimal canónico, opcional)
- `grade` (Decimal canónico, opcional)
- `unit` (opcional)
- `feedback` (opcional, solo si el contrato académico lo permite)

### C2 `finalOutcome`

```json
{
  "value": "6.4",
  "unit": "grade",
  "resultState": "finalized",
  "finalizable": true
}
```

### Reglas

- Orden determinista (por `assessmentId` lexicográfico).
- `score`/`grade` son representaciones decimales canónicas (strings), nunca floats.
- No se adivinan conversiones score/grade.
- No se mezcla semántica legacy con grade-policy.
- No incluye: datos de otros estudiantes, cohort statistics, traces, prompts,
  evidenceRefs privadas, provenance completo, email, RUT, AVA user, submissions, paths
  privados, información de docente, capability key.

### Identity

Si `displayName` se usa en la UI, se resuelve desde IdentityStore y se almacena solo
dentro del payload cifrado o proyección autenticada, con `identityProjectionHash`
registrado. Drift de identidad antes de publish bloquea.

## 3. Release Plan V1

Plan privado del release de portal, por estudiante.

```json
{
  "schemaVersion": "1.0.0",
  "releaseId": "prelease_...",
  "sectionId": "CUR0001-001",
  "publicationId": "pub_...",
  "portalMode": "static-encrypted",
  "portalAppVersion": "1.0.0",
  "snapshot": {
    "contentHash": "...",
    "reviewHash": "...",
    "mode": "legacy-effective"
  },
  "hostingProfileId": "local-static-v1",
  "releaseHash": "...",
  "objectCount": 3,
  "objects": [
    {
      "studentId": "stu_...",
      "objectId": "...",
      "projectionHash": "...",
      "artifactHash": "...",
      "metadataHash": "..."
    }
  ],
  "manifest": {
    "files": {
      "plan.json": {"sha256": "..."},
      "capability-manifest.json": {"sha256": "..."}
    }
  }
}
```

Invariantes:

- `releaseId` = `"prelease_" + releaseIntentHash[:24]`.
- `objectCount` = número de estudiantes con proyección.
- Los `objects[]` NO contienen la capability key.
- El `capability-manifest.json` privado sí contiene las keys (0600, bajo private_root).

## 4. PortalHostingProfile V1

```json
{
  "schemaVersion": "1.0.0",
  "profileId": "local-static-v1",
  "mode": "static-encrypted",
  "baseUrl": "https://portal.example.test/",
  "tlsRequired": true,
  "directoryListingDisabled": true,
  "headerPolicy": {
    "contentSecurityPolicy": "default-src 'none'; ...",
    "referrerPolicy": "no-referrer",
    "xContentTypeOptions": "nosniff",
    "noindex": true
  },
  "cachePolicy": {
    "mode": "private-no-store"
  },
  "supportsAtomicPromotion": true,
  "supportsDelete": true,
  "supportsPurge": true,
  "authorizationModel": null
}
```

### static-encrypted exige

- `tlsRequired = true`
- `directoryListingDisabled = true`
- `noindex`, `no-referrer`, `nosniff`, CSP compatible, cache policy explícita.

### authenticated exige

- `authorizationModel = "subject-bound"`
- `cachePolicy.mode = "private-no-store"`
- `tlsRequired = true`
- `crossStudentAccess = denied`
- No anonymous object access.

Preflight falla cerrado si no se cumplen.

## 5. PortalApproval V1

```json
{
  "releaseId": "prelease_...",
  "releaseHash": "...",
  "objectCount": 3,
  "approvedBy": "user:approver-1",
  "approvedAt": "2026-08-03T00:00:00Z",
  "confirmation": "confirm-reviewed",
  "status": "approved"
}
```

Invariantes de approval:

- Bundle completo verificado.
- `releaseHash` recalculado y coincidente.
- `objectCount` exacto.
- Snapshot nuevamente íntegro y `approved`.
- `identityProjectionHash` sin drift.
- Hosting profile válido.
- `actor` no vacío, no email, sanitizado.
- `--confirm-reviewed` obligatorio y debe ser `True` en el dominio.
- Approval persistida en SQLite.
- No auto-approval.

## 6. Receipts

### Publish receipt

```json
{
  "receiptId": "rcpt_...",
  "type": "publish",
  "releaseId": "prelease_...",
  "releaseHash": "...",
  "hostingProfileId": "local-static-v1",
  "publisherType": "local-static",
  "publishedAt": "...",
  "objectCount": 3,
  "deploymentReference": "...",
  "artifactManifestHash": "...",
  "result": "published"
}
```

### Revoke receipt

```json
{
  "receiptId": "rcpt_...",
  "type": "revoke",
  "releaseId": "prelease_...",
  "revokedAt": "...",
  "actor": "user:ops-1",
  "reason": "sanitized reason",
  "requestedObjects": 3,
  "removedObjects": 3,
  "unavailableObjects": 0,
  "cacheLimitations": "revoke does not invalidate previously downloaded copies"
}
```

### Purge receipt

```json
{
  "receiptId": "rcpt_...",
  "type": "purge",
  "releaseId": "prelease_...",
  "purgedAt": "...",
  "actor": "user:ops-1",
  "removedObjects": 3,
  "missingObjects": 0,
  "retainedAuditRecords": true,
  "externalLimitations": "external caches are not guaranteed to be cleared"
}
```

### Nunca en un receipt

Capability key, capability URL, studentId mapping, displayName, email, score, grade,
feedback.

## 7. Hashing

### releaseIntentHash

```
releaseIntentHash = SHA-256(
  sectionId + publicationId + snapshotContentHash + snapshotReviewHash
  + snapshotMode + portalAppVersion + hostingProfileHash + portalMode)
```

`releaseId = "prelease_" + releaseIntentHash[:24]`.

El releaseId representa intención lógica estable. Primera preparación genera object IDs,
keys y nonces y persiste el bundle privado completo. Prepare repetido con la misma
intención verifica el bundle existente y retorna el mismo release sin generar keys nuevas
ni modificar artifacts.

### projectionHash

`SHA-256(canonical JSON de la StudentPortalView del estudiante)`.

### artifactHash

`SHA-256` de los bytes reales de cada artifact público (index.html, app.js, styles.css,
payload.enc, metadata.json).

### capabilityManifestHash

`SHA-256(canonical JSON del capability manifest privado excluyendo la key)`.

### releaseHash

Cubre: snapshot hashes, portal mode, hosting profile, portal app version, cada
projectionHash, cada objectId, cada ciphertext hash, cada metadata hash,
capabilityManifestHash, manifest del public bundle y object count.

Cambiar cualquier dato, objeto, key binding o artifact cambia releaseHash.

### identityProjectionHash

Misma convención que C3:

```
SHA-256(canonical JSON de {studentId, displayName, contactEmail})
```

## 8. Static encrypted mode — estructura pública

Por estudiante, bajo `<deployment>/<publicationId>/<objectId>/`:

```text
<objectId>/
├── index.html
├── app.js
├── styles.css
├── payload.enc
└── metadata.json
```

`metadata.json` puede incluir:

```json
{
  "schemaVersion": "1.0.0",
  "algorithm": "AES-256-GCM",
  "nonce": "<base64url>",
  "aad": "<base64url>",
  "ciphertextSha256": "...",
  "portalAppVersion": "1.0.0"
}
```

`metadata.json` NO puede incluir: studentId, displayName, email, RUT, grade, score,
feedback, capability key.

### AAD canónico

```
AAD = canonical JSON de {
  schemaVersion, releaseId, sectionId, publicationId,
  objectId, portalViewSchemaVersion, portalAppVersion
}
```

No se incluye studentId en metadata ni AAD público.

### Cifrado

```
ciphertext = AESGCM(key).encrypt(nonce, canonicalPayloadBytes, canonicalAADBytes)
```

`canonicalPayloadBytes` = serialización canónica de la StudentPortalView.

## 9. Static app

La aplicación estática:

1. Lee la key desde `location.hash`.
2. Valida base64url y longitud (256 bits).
3. Elimina el fragmento con `history.replaceState`.
4. Carga `metadata.json` y `payload.enc`.
5. Reconstruye el AAD canónico.
6. Descifra con Web Crypto AES-GCM.
7. Valida StudentPortalView.
8. Renderiza usando `textContent`.
9. No realiza solicitudes adicionales.
10. Muestra errores genéricos sin datos sensibles.

Prohibido: `innerHTML` con contenido académico, `eval`, `Function`, scripts remotos,
CDN, analytics, fonts remotas, `localStorage`/`sessionStorage` para la key, service
workers en V1, copiar la capability a logs.

Headers requeridos: `Content-Security-Policy`, `Referrer-Policy: no-referrer`,
`X-Content-Type-Options: nosniff`, `Cache-Control` explícito, `noindex`.
Meta tags requeridos: `robots noindex,nofollow,noarchive`, `referrer no-referrer`.
Los meta tags no sustituyen los headers HTTP reales; el hosting profile indica cómo se
aplican.

## 10. Authenticated adapter contract

```python
class AuthenticatedPublisher(Protocol):
    def preflight(self, profile) -> None: ...
    def publish_subject_projection(self, subject: OpaqueSubject, projection_payload: bytes,
                                   metadata: dict, profile) -> AuthenticatedReceipt: ...
    def verify_subject_access(self, subject: OpaqueSubject, reference: str, profile) -> bool: ...
    def revoke(self, subject: OpaqueSubject, reference: str, profile) -> RevokeOutcome: ...
    def purge(self, subject: OpaqueSubject, reference: str, profile) -> PurgeOutcome: ...
```

Reference/fake adapter:

- Mantiene projections separadas por studentId opaco.
- Exige authenticated subject.
- Subject A no puede leer B.
- Subject inexistente recibe denegación genérica.
- No expone listado global.
- No permite anonymous access.
- Registra receipts sin payload.

El contrato permite incorporar posteriormente adapters como Firebase, Supabase,
Cloudflare o una API propia sin modificar StudentPortalView ni el release plan.

## 11. Prohibiciones transversales

- No existe dataset global servible.
- Cada estudiante tiene un artefacto independiente.
- No hay `--force`, auto-approval, `--plaintext` ni `--short-code`.
- La capability viaja solo en `location.hash`, nunca en query string.
- No se guardan capabilities en logs, receipts o SQLite.
