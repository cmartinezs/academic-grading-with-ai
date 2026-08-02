# C3 Verification Report

## Status: COMPLETE

## Branch
- feat/c3-email-delivery
- Base: master (f3d1c755fd753c65ddb1b6ea5e7814f9218ca42f)

## Contracts Verified

| Contract | Status | Details |
|---|---|---|
| Template V1 | Pass | Schema validation, placeholder allow-list, CRLF rejection |
| StudentEmailView V1 | Pass | Legacy-effective and grade-policy-effective modes |
| Plan V1 | Pass | Deterministic previewHash, planId derivation, recipient ordering |
| Approval V1 | Pass | previewHash binding, recipientCount check, actor validation |
| Ledger V1 | Pass | State machine transitions, idempotency, concurrency |
| Transport V1 | Pass | Fake transport all behaviors, SMTP error classification |

## Storage

| Root | Classification | Permissions |
|---|---|---|
| private_root/email/plans/ | PII | 0700/0600 |
| state_root/email/email-ledger.sqlite3 | Operational | 0600 |
| state_root/email/locks/ | Operational | 0700 |
| state_root/email/backups/ | Operational | 0700 |
| temp_root/email-plan-staging/ | Ephemeral | 0700 |

## Hashing

| Hash | Algorithm | Verified |
|---|---|---|
| itemHash | SHA-256(canonical recipient JSON) | Yes |
| previewHash | SHA-256(canonical plan core JSON) | Yes |
| planId | "eplan_" + previewHash[:24] | Yes |
| idempotencyKey | SHA-256(sectionId+publicationId+studentId+normalizedRecipient+templateId+templateVersion+intent) | Yes |
| identityProjectionHash | SHA-256(studentId+displayName+contactEmail) | Yes |

## State Machine

| From | To | Verified |
|---|---|---|
| absent | reserved | Yes |
| reserved | sending | Yes |
| sending | sent | Yes |
| sending | failedTransient | Yes |
| sending | failedPermanent | Yes |
| sending | ambiguous | Yes |
| failedTransient | retryAuthorized | Yes |
| retryAuthorized | reserved | Yes |
| ambiguous | sent (manual) | Yes |
| ambiguous | retryAuthorized (manual) | Yes |

## Transport Error Taxonomy

| Category | Scope | Retryability | Delivery Certainty | Verified |
|---|---|---|---|---|
| Template/schema invalid | batch | permanent | notSent | Yes |
| SMTP auth/config/TLS | batch | permanent | notSent | Yes |
| Connection/rate limit | batch | transient | notSent | Yes |
| Recipient refused 5xx | recipient | permanent | notSent | Yes |
| Recipient 4xx transient | recipient | transient | notSent | Yes |
| Timeout/disconnect | recipient | — | unknown | Yes |
| Provider accepted | recipient | — | delivered | Yes |

## Tests

Command: `PYTHONPATH=engine pytest engine/email_delivery/tests/ -v`
Result: **96 passed** in ~1.6s

## Concurrency

- Concurrent reserve of same idempotency key: one succeeds, one gets IdempotencyConflictError.
- Concurrent reserve of different keys: both succeed.
- SQLite WAL mode allows concurrent reads during writes.

## Failure Injection

| Scenario | Final State | Verified |
|---|---|---|
| Crash after reserved | retryAuthorized (via reconcile) | Yes |
| Crash after sending | ambiguous (via reconcile) | Yes |
| Permanent failure | failedPermanent (terminal) | Yes |
| Ambiguous delivery | ambiguous (no auto-retry) | Yes |

## Privacy

- Logs: no full email, no body, no feedback, no displayName.
- Ledger: stores maskedRecipient, never full email.
- Previews: stored only in private_root.
- SMTP password: only from environment variable.
- C0 scanner: passes on all C3 code and fixtures.

## Compatibility

- C1 snapshot (legacy-effective): StudentEmailView reads canonical/results.json.
- C2 snapshot (grade-policy-effective): StudentEmailView reads canonical/outcomes.json.
- C0 regression: 92 tests pass.
- C1 regression: 119 tests pass.
- C2 regression: 199 tests pass.

## Out of Scope

- C4 portal
- C5 teacher/BI
- C6 conventions
- C7 discovery
- HTML email
- Attachments
- CC/BCC
- Multi-recipient per message
- Auto-approval
- --force
