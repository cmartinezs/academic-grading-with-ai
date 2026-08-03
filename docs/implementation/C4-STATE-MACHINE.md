# C4 Portal State Machine

## 1. Storage

SQLite 3 via `sqlite3` estándar.

Archivo: `state_root/portal/portal-ledger.sqlite3` (0600).
Directorio: `state_root/portal/` (0700).

### Configuración

```sql
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;
```

## 2. Tablas mínimas

```sql
CREATE TABLE releases (
    releaseId           TEXT PRIMARY KEY,
    releaseHash         TEXT NOT NULL,
    releaseIntentHash   TEXT NOT NULL,
    sectionId           TEXT NOT NULL,
    publicationId       TEXT NOT NULL,
    snapshotMode        TEXT NOT NULL,
    portalMode          TEXT NOT NULL,
    portalAppVersion    TEXT NOT NULL,
    hostingProfileId    TEXT NOT NULL,
    objectCount         INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'prepared',
    createdAt           TEXT NOT NULL,
    updatedAt           TEXT NOT NULL
);

CREATE TABLE approvals (
    approvalId      INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    releaseHash     TEXT NOT NULL,
    objectCount     INTEGER NOT NULL,
    approvedBy      TEXT NOT NULL,
    approvedAt      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'approved',
    UNIQUE(releaseId, releaseHash)
);

CREATE TABLE publish_runs (
    runId           INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    idempotencyKey  TEXT NOT NULL UNIQUE,
    hostingProfileId TEXT NOT NULL,
    publisherType   TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'publishing',
    startedAt       TEXT NOT NULL,
    completedAt     TEXT,
    receiptId       TEXT
);

CREATE TABLE published_objects (
    objectId        TEXT NOT NULL,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    projectionHash  TEXT NOT NULL,
    artifactHash    TEXT NOT NULL,
    deployedAt      TEXT NOT NULL,
    PRIMARY KEY (releaseId, objectId)
);

CREATE TABLE receipts (
    receiptId       TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    payload         TEXT NOT NULL,
    createdAt       TEXT NOT NULL
);

CREATE TABLE lifecycle_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    event           TEXT NOT NULL,
    actor           TEXT NOT NULL,
    reason          TEXT,
    at              TEXT NOT NULL
);

CREATE TABLE reconciliation_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL,
    finding         TEXT NOT NULL,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE hosting_profiles (
    profileId       TEXT PRIMARY KEY,
    profileHash     TEXT NOT NULL,
    mode            TEXT NOT NULL,
    profileJson     TEXT NOT NULL,
    firstSeenAt     TEXT NOT NULL
);
```

## 3. Estados del release

| Estado | Significado | Terminal |
|---|---|---|
| `prepared` | Bundle privado completo, no aprobado | No |
| `approved` | Aprobación humana ligada al releaseHash exacto | No |
| `publishing` | Batch de publish en curso | No |
| `published` | Deploy completado con receipt | Sí (por releaseHash) |
| `partial` | Deploy incompleto detectado | No |
| `blocked` | Gate bloquea la operación | Sí |
| `revoked` | Se ordenó retirar accesos | Sí |
| `purged` | Objetos eliminados bajo control del publisher | Sí |

## 4. Transiciones

```
prepared ──approve──▶ approved
approved ──publish──▶ publishing ──complete──▶ published
publishing ──fail/interrupt──▶ partial (reconcilable)
prepared/approved ──gate failure──▶ blocked
published ──revoke──▶ revoked
revoked ──purge──▶ purged
```

### Reglas

- `published` es idempotente para el mismo `releaseHash` (misma idempotency key).
- `releaseHash` diferente no reutiliza la publicación.
- `revoked` no vuelve a `published`.
- `purged` no vuelve a `published`.
- Una nueva publicación requiere un nuevo release.
- No se borra history para habilitar republish.
- No se guardan capabilities, payload, nombres ni notas en el ledger.

## 5. Idempotency key mínima

```
idempotencyKey = SHA-256(
  releaseId + releaseHash + hostingProfileId + publisherType)
```

## 6. Concurrencia

- `publish_runs.idempotencyKey UNIQUE` garantiza un único ganador en publish.
- Transiciones condicionales (`UPDATE ... WHERE state = ?`) previenen doble promoción.
- No se mantiene transacción durante el deploy a filesystem.
- `PRAGMA integrity_check` y `foreign_key_check` disponibles en `ledger-check`.

## 7. Datos nunca almacenados en el ledger

- Capability key.
- Capability URL.
- Payload cifrado o descifrado.
- displayName.
- score, grade, feedback.
- RUT, email.

## 8. Datos almacenados en el ledger

- Opaque IDs (releaseId, objectId, studentId no mapeado en receipts).
- releaseHash, releaseIntentHash, projectionHash, artifactHash, artifactManifestHash.
- Timestamps, estado, actor, publisherType, hostingProfileId.
- Resultados de revoke/purge (conteos, no mapeos).
