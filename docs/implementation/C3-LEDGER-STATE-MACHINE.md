# C3 Ledger State Machine

## 1. Storage

SQLite 3 via Python `sqlite3` standard library.

File: `state_root/email/email-ledger.sqlite3`
Permissions: 0600
Directory: `state_root/email/` (0700)

### Configuration

```sql
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;
```

## 2. Tables

### plans

```sql
CREATE TABLE plans (
    planId              TEXT PRIMARY KEY,
    sectionId           TEXT NOT NULL,
    publicationId       TEXT NOT NULL,
    snapshotContentHash TEXT NOT NULL,
    snapshotReviewHash  TEXT NOT NULL,
    snapshotMode        TEXT NOT NULL,
    templateId          TEXT NOT NULL,
    templateVersion     TEXT NOT NULL,
    templateHash        TEXT NOT NULL,
    intent              TEXT NOT NULL,
    senderProfileId     TEXT NOT NULL,
    fromAddress         TEXT NOT NULL,
    replyTo             TEXT,
    previewHash         TEXT NOT NULL,
    recipientCount      INTEGER NOT NULL,
    planPath            TEXT NOT NULL,
    createdAt           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    CHECK (recipientCount > 0)
);
```

### approvals

```sql
CREATE TABLE approvals (
    approvalId      INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL REFERENCES plans(planId),
    previewHash     TEXT NOT NULL,
    recipientCount  INTEGER NOT NULL,
    approvedBy      TEXT NOT NULL,
    approvedAt      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'approved',
    UNIQUE(planId, previewHash)
);
```

### deliveries

```sql
CREATE TABLE deliveries (
    deliveryId          INTEGER PRIMARY KEY AUTOINCREMENT,
    planId              TEXT NOT NULL REFERENCES plans(planId),
    studentId           TEXT NOT NULL,
    idempotencyKey      TEXT NOT NULL UNIQUE,
    normalizedRecipient TEXT NOT NULL,
    maskedRecipient     TEXT NOT NULL,
    identityProjectionHash TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'reserved',
    attemptCount        INTEGER NOT NULL DEFAULT 0,
    lastAttemptAt       TEXT,
    providerMessageId   TEXT,
    clientMessageId     TEXT NOT NULL,
    createdAt           TEXT NOT NULL,
    updatedAt           TEXT NOT NULL
);
```

### delivery_attempts

```sql
CREATE TABLE delivery_attempts (
    attemptId       INTEGER PRIMARY KEY AUTOINCREMENT,
    deliveryId      INTEGER NOT NULL REFERENCES deliveries(deliveryId),
    attemptNumber   INTEGER NOT NULL,
    stateBefore     TEXT NOT NULL,
    stateAfter      TEXT NOT NULL,
    transportCode   TEXT,
    errorClass      TEXT,
    deliveryCertainty TEXT,
    providerMessageId TEXT,
    clientMessageId TEXT,
    attemptedAt     TEXT NOT NULL,
    UNIQUE(deliveryId, attemptNumber)
);
```

### template_versions

```sql
CREATE TABLE template_versions (
    templateId      TEXT NOT NULL,
    templateVersion TEXT NOT NULL,
    templateHash    TEXT NOT NULL,
    firstSeenAt     TEXT NOT NULL,
    PRIMARY KEY (templateId, templateVersion)
);
```

### reconciliation_events

```sql
CREATE TABLE reconciliation_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL,
    deliveryId      INTEGER REFERENCES deliveries(deliveryId),
    studentId       TEXT,
    idempotencyKey  TEXT,
    fromState       TEXT NOT NULL,
    toState         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    reconciledAt    TEXT NOT NULL
);
```

### batch_runs

```sql
CREATE TABLE batch_runs (
    batchRunId      INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL REFERENCES plans(planId),
    previewHash     TEXT NOT NULL,
    transportType   TEXT NOT NULL,
    startedAt       TEXT NOT NULL,
    completedAt     TEXT,
    totalRecipients INTEGER NOT NULL,
    sentCount       INTEGER NOT NULL DEFAULT 0,
    failedCount     INTEGER NOT NULL DEFAULT 0,
    ambiguousCount  INTEGER NOT NULL DEFAULT 0,
    skippedCount    INTEGER NOT NULL DEFAULT 0,
    outcome         TEXT,
    actor           TEXT NOT NULL
);
```

## 3. Delivery States

| State | Meaning | Terminal | Auto-retry |
|---|---|---|---|
| `reserved` | Idempotency key claimed, not yet sending | No | Orphan → `retryAuthorized` |
| `sending` | Transport invocation in progress | No | Orphan → `ambiguous` |
| `sent` | Provider accepted delivery | Yes | Never |
| `failedTransient` | Temporary failure, retry possible | No | Manual only |
| `failedPermanent` | Permanent failure | Yes | Never |
| `ambiguous` | Delivery outcome unknown | No | Manual only |
| `paused` | Batch paused (global transient) | No | Manual resume |
| `retryAuthorized` | Retry explicitly authorized | No | Next execute |

## 4. State Transitions

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
   absent ──→ reserved ──→ sending ──→ sent (terminal)        │
                    │            │                             │
                    │            ├──→ failedTransient          │
                    │            │         │                   │
                    │            │         └──→ retryAuthorized│
                    │            │                  │          │
                    │            │                  └──→ reserved (loop back)
                    │            │                             │
                    │            ├──→ failedPermanent (terminal)
                    │            │                             │
                    │            └──→ ambiguous               │
                    │                         │               │
                    │                         └──→ manual resolve
                    │                              ├──→ sent
                    │                              └──→ not-sent → retryAuthorized
                    │                                             │
                    └──→ (orphan) ──→ retryAuthorized ──────────┘
```

### Transition Rules

| From | To | Trigger | Condition |
|---|---|---|---|
| absent | reserved | execute | idempotencyKey not in deliveries |
| reserved | sending | execute | same process holds reservation |
| sending | sent | transport accepted | receipt.accepted == True |
| sending | failedTransient | transport 4xx | retryability == transient |
| sending | failedPermanent | transport 5xx | retryability == permanent |
| sending | ambiguous | timeout/disconnect | deliveryCertainty == unknown |
| failedTransient | retryAuthorized | manual | explicit authorization |
| retryAuthorized | reserved | execute | re-enter execute flow |
| reserved | retryAuthorized | reconcile | orphan detection |
| sending | ambiguous | reconcile | orphan detection |
| ambiguous | sent | resolve-ambiguous | decision == sent, human confirm |
| ambiguous | retryAuthorized | resolve-ambiguous | decision == not-sent, human confirm |

### Invariants

1. `sent` is terminal: no transition out of `sent` for a given `idempotencyKey`.
2. `failedPermanent` is terminal: no automatic transition out.
3. `ambiguous` never auto-retries.
4. No two concurrent processes can hold `sending` for the same `idempotencyKey`.
5. Every transition creates a `delivery_attempts` record.
6. `delivery.attemptCount` equals the number of `delivery_attempts` rows.
7. Historical records are never deleted to enable re-delivery.

## 5. Concurrency Control

- `deliveries.idempotencyKey` UNIQUE constraint prevents double reservation.
- Reserve: `INSERT INTO deliveries (idempotencyKey, ...) VALUES (...)` —
  fails with `IntegrityError` if key exists.
- State transitions: `UPDATE deliveries SET state = ? WHERE deliveryId = ? AND state = ?`
  — conditional update ensures correct from-state.
- No transaction held during SMTP call.
- SQLite WAL mode allows concurrent reads during writes.

## 6. Data Never Stored in Ledger

- Email body
- Complete subject line
- Complete recipient email
- displayName
- Feedback text
- SMTP password
- Any PII beyond maskedRecipient

## 7. Data Stored in Ledger

- Opaque IDs (planId, studentId, idempotencyKey)
- previewHash
- maskedRecipient
- Timestamps
- State
- Attempt number
- Transport code
- providerMessageId (optional)
- clientMessageId
- errorClass
- deliveryCertainty
- identityProjectionHash

## 8. Integrity Verification

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

Additional checks:
- No deliveries in invalid states.
- No delivery_attempts without corresponding delivery.
- No `sending` state older than a configurable timeout without reconciliation.
- Plan references valid (planId exists in plans table).
- Approval references valid (planId + previewHash match).
