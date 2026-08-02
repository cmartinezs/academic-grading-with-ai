# C3 Implementation Plan — Email Delivery Workflow

## 1. Objective

Implement prepare/approve/execute email delivery with preview-hash approval,
idempotency, durable SQLite ledger, and safe crash recovery. V1 profile:
text/plain, one recipient per message, no HTML/attachments/CC/BCC.

## 2. Functional Profile V1

| Capability | Included | Excluded |
|---|---|---|
| Prepare plan from approved snapshot | Yes | — |
| Preview per-recipient | Yes | — |
| Human approval bound to previewHash | Yes | — |
| Execute with fake transport | Yes | — |
| Execute with SMTP transport | Yes | — |
| Idempotent re-execute | Yes | — |
| Reconciliation of orphan states | Yes | — |
| Manual ambiguous resolution | Yes | — |
| HTML body | No | C3 V1 |
| Attachments | No | C3 V1 |
| CC / BCC | No | C3 V1 |
| Multi-recipient per message | No | C3 V1 |
| Auto-approval | No | Never |
| `--force` global | No | Never |
| C4 portal | No | C4 |
| C5 teacher/BI | No | C5 |
| C6 conventions | No | C6 |
| C7 discovery | No | C7 |

## 3. Roots and Artifact Classification

| Artifact | Root | Classification | Permissions | Retention |
|---|---|---|---|---|
| Plan bundle (plan.json, previews) | `private_root/email/plans/<sectionId>/<publicationId>/<planId>/` | PII | 0700 dir / 0600 file | While deliveries exist |
| Email ledger | `state_root/email/email-ledger.sqlite3` | Operational state | 0600 | Indefinite (backup API) |
| Email locks | `state_root/email/locks/` | Operational state | 0700 | Ephemeral |
| Email backups | `state_root/email/backups/` | Operational state | 0700 | Per policy |
| Plan staging | `temp_root/email-plan-staging/<operationId>/` | Ephemeral | 0700 | Until promotion or discard |
| Template definitions | Repository (`engine/email_delivery/templates/`) | Public | Versioned | Permanent |
| Template schemas | Repository (`engine/email_delivery/schemas/`) | Public | Versioned | Permanent |
| Sender profiles | `private_root/email/sender-profiles/` | PII | 0600 | While referenced |

**Never stored in**: repository, publications, exports, logs, CI artifacts.

## 4. Contracts

### 4.1 Template Contract

See `C3-EMAIL-CONTRACT.md` §2.

### 4.2 Plan Contract

See `C3-EMAIL-CONTRACT.md` §3.

### 4.3 Approval Contract

See `C3-EMAIL-CONTRACT.md` §4.

### 4.4 Ledger Contract

See `C3-LEDGER-STATE-MACHINE.md`.

### 4.5 Transport Contract

See `C3-EMAIL-CONTRACT.md` §5.

### 4.6 StudentEmailView Contract

See `C3-EMAIL-CONTRACT.md` §6.

## 5. Recipient Normalization

1. Trim exterior whitespace.
2. Reject CR, LF, and all C0 control characters.
3. Reject embedded display-name (e.g. `"Name" <addr>`).
4. Reject CC/BCC indicators and list syntax.
5. Preserve local-part exactly (case-sensitive per RFC 5321).
6. Normalize domain to lowercase.
7. Apply IDNA encoding for international domains.
8. Validate basic `local@domain` structure.

## 6. PreviewHash

```
itemHash     = SHA-256(canonical JSON of single recipient payload)
previewHash  = SHA-256(canonical JSON of complete plan core)
planId       = "eplan_" + first 24 hex chars of previewHash
```

The plan core includes: schemaVersion, planId, sectionId, publicationId,
snapshotContentHash, snapshotReviewHash, snapshotMode, templateId,
templateVersion, templateHash, intent, senderProfileId, fromAddress,
replyTo, recipientCount, and the sorted recipients array.

Each recipient in the core includes: studentId, normalizedRecipient,
maskedRecipient, identityProjectionHash, subject, textBody, itemHash,
idempotencyKey.

**No timestamps in the core determinista.** Clock values are recorded
outside the core (in metadata) and do not affect hashes.

## 7. Idempotency Key

```
idempotencyKey = SHA-256(
  sectionId
  + publicationId
  + studentId
  + normalizedRecipient
  + templateId
  + templateVersion
  + intent
)
```

Semantic: changing any component creates a new key. Same inputs always
produce the same key. A `sent` state for a key is terminal.

## 8. Lifecycle Gates

| Operation | Required snapshot state | Blocked states |
|---|---|---|
| prepare | approved | nonexistent, created, reviewed, revoked, corrected, superseded |
| approve | approved (re-verified) | any terminal |
| execute | approved (re-verified) | any terminal |
| status | any | — |
| reconcile | any | — |
| resolve-ambiguous | any | — |

A snapshot transitioning to terminal during execute: the current
recipient may complete; no further recipients are initiated.

## 9. State Machine

See `C3-LEDGER-STATE-MACHINE.md` for full specification.

Key invariants:
- `sent` is terminal per idempotency key.
- `ambiguous` never auto-retries.
- `failedPermanent` never auto-retries.
- `reserved` orphan → `retryAuthorized` (safe-to-retry).
- `sending` orphan → `ambiguous` (delivery unknown).
- No two concurrent processes can hold `sending` for the same key.

## 10. Crash/Recovery Model

| Crash point | State | Recovery |
|---|---|---|
| Before staging promotion | No plan | Re-prepare (idempotent) |
| After promotion, before approval | Plan exists, no approval | Approve or discard |
| After approval, before first delivery | Approved, no deliveries | Execute (idempotent) |
| After `reserved`, before `sending` | `reserved` | Reconcile → `retryAuthorized` |
| After `sending`, before transport response | `sending` | Reconcile → `ambiguous` |
| After transport accept, before `sent` persist | `sending` | Reconcile → `ambiguous` |
| After `sent` persist | `sent` | Terminal; no action needed |
| After `failedTransient` | `failedTransient` | Manual retry authorization |
| After `failedPermanent` | `failedPermanent` | No auto-retry |

**Central rule**: when in doubt about delivery → `ambiguous`, never automatic retry.

## 11. Transport Error Taxonomy

| # | Category | Scope | Retryability | Delivery Certainty | Example |
|---|---|---|---|---|---|
| 1 | Template/schema invalid | batch | permanent | notSent | Missing placeholder |
| 2 | SMTP auth/config/TLS | batch | permanent | notSent | Auth rejected |
| 3 | Connection/rate limit | batch | transient | notSent | 421 rate limit |
| 4 | Recipient refused 5xx | recipient | permanent | notSent | 550 mailbox not found |
| 5 | Recipient 4xx transient | recipient | transient | notSent | 450 mailbox busy |
| 6 | Timeout/disconnect unknown | recipient | — | unknown | Connection lost mid-send |
| 7 | Provider accepted | recipient | — | delivered | 250 OK |

## 12. Privacy and Masking

- `mask_email("user@example.com")` → `"u***@example.com"`
- Logs: never include full email, body, feedback, displayName, RUT.
- Ledger: stores `maskedRecipient`, never full email.
- Previews: stored only in `private_root`, never in exports/publications.
- SMTP credentials: only from environment variables, never CLI args, logs, or versioned files.
- C0 scanner must pass on all C3 code and fixtures.

## 13. Retention and Backup

- Ledger backup via SQLite backup API (`sqlite3.Connection.backup()`).
- Backup directory: `state_root/email/backups/`.
- Plan bundles retained while any delivery record references them.
- Purge requires explicit confirmation and only affects plans with
  all deliveries in terminal states (`sent`, `failedPermanent`).
- Ledger never deleted; backup/restore is the operational pattern.

## 14. Compatibility with C1 and C2 Snapshots

- C3 reads `canonical/subjects.json` from the approved snapshot (C1/C2 format).
- C3 reads `canonical/results.json` for legacy-effective mode (C1).
- C3 reads `canonical/outcomes.json` for grade-policy-effective mode (C2).
- C3 reads `manifest.json` for `contentHash` and `reviewHash`.
- C3 reads the lifecycle ledger to verify snapshot state.
- C3 does not modify any snapshot artifact.
- C3 does not break any C0, C1, or C2 contract.

## 15. Out of Scope

- C4 student portal
- C5 teacher/BI dashboards
- C6 convention enforcement
- C7 discovery
- HTML email bodies
- Attachments
- CC / BCC
- Multi-recipient per message
- Jinja or dynamic template evaluation
- Auto-approval
- `--force` global flag
- Bulk ambiguous resolution without review
- Email open/click tracking
