# C3 Verification Report

## Status: COMPLETE

## Verified head

- Branch: `feat/c3-email-delivery`
- Base: `master` (`e2cd008119ce3ade495993b8eaa8e64ef7ce958c`)
- Head: `a7bfa2c7230ff5fced74ac56d6364a4da343f7ac`
- Pull request: #6, Draft
- Remote CI: C0, C1, C2 and C3 successful

## Contracts verified

| Contract | Status | Details |
|---|---|---|
| Template V1 | Pass | Schema validation, placeholder allow-list, CRLF rejection and template identity registry |
| StudentEmailView V1 | Pass | Legacy-effective and grade-policy-effective modes |
| Plan V1 | Pass | Deterministic previewHash, planId derivation, recipient ordering and atomic private promotion |
| Approval V1 | Pass | Exact bundle, source snapshot, previewHash, recipient count and actor binding |
| Ledger V1 | Pass | State machine, durable idempotency, recovery and multiprocess execution |
| Transport V1 | Pass | Exact effective config, STARTTLS/implicit TLS, fake transport and SMTP classification |
| Publication Snapshot boundary | Pass | Canonical C1 verifier with immutable, manifest, semantic, privacy and lifecycle gates |

## Storage

| Root | Classification | Permissions |
|---|---|---|
| `private_root/email/plans/` | PII/private approved payload | 0700 directories / 0600 files |
| `private_root/email/plans/.../.staging/` | Private ephemeral staging on same filesystem | 0700 directories / 0600 files |
| `state_root/email/email-ledger.sqlite3` | Operational | 0600 |
| `state_root/email/locks/` | Operational | 0700 |
| `state_root/email/backups/` | Operational | 0700 |
| `state_root/email/recovery/` | Operational recovery markers | 0700 directories / 0600 files |

Recovery markers are outside the immutable plan bundle and contain only opaque IDs, counts, outcome and sanitized error class/code.

## Hashing

| Hash | Algorithm | Verified |
|---|---|---|
| itemHash | SHA-256(canonical recipient JSON) | Yes |
| previewHash | SHA-256(canonical plan core JSON) | Yes |
| planId | `eplan_` + previewHash[:24] | Yes |
| idempotencyKey | SHA-256(sectionId+publicationId+studentId+normalizedRecipient+templateId+templateVersion+intent) | Yes |
| identityProjectionHash | SHA-256(studentId+displayName+normalized contactEmail) | Yes |

## Source snapshot authority

`verify_email_source_snapshot` delegates to the C1 canonical verifier:

```python
publication.verify.verify_snapshot(
    snapshot_dir,
    section_id=section_id,
    publication_id=publication_id,
    immutable=True,
)
```

Prepare, approve and execute all verify:

- JSON contracts and semantic references;
- privacy/classification gates;
- manifest file hashes and sizes;
- recomputed contentHash and reviewHash;
- exact sectionId and publicationId;
- approved immutable file permissions;
- canonical policy mode;
- lifecycle state exactly `approved`.

Approve and execute compare the verified snapshot fields with the immutable values stored in the plan. Tampering after prepare blocks approval; tampering after approval blocks execution with zero transport calls.

## State machine

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

## Transport error taxonomy

| Category | Scope | Retryability | Delivery certainty | Verified |
|---|---|---|---|---|
| Template/schema invalid | batch | permanent | notSent | Yes |
| SMTP auth/config/TLS | batch | permanent | notSent | Yes |
| Connection/rate limit | batch | transient | notSent | Yes |
| Recipient refused 5xx | recipient | permanent | notSent | Yes |
| Recipient 4xx transient | recipient | transient | notSent | Yes |
| Timeout/disconnect | recipient | transient | unknown | Yes |
| Provider accepted | recipient | — | delivered | Yes |

## Tests

| Suite | Result |
|---|---:|
| C3 unit, contract, integration, privacy, failure and concurrency | 199 passed |
| C2 regression | 199 passed |
| C1 regression | 120 passed, 1 intentionally skipped and replaced by two deterministic ordering tests |
| C0 regression | 92 passed |
| Strict scanner | 279 files, BLOCK=0, REVIEW=0 |

C1 E2E also passed. The former probabilistic generate-versus-terminal race was replaced by explicit generate-first and terminal-first tests.

## Concurrency

- Concurrent reservation of the same idempotency key yields one winner.
- Multiprocess execute of the same plan/key produces exactly one transport send.
- Two plans with the same semantic key produce at most one send.
- Concurrent retryAuthorized produces one send.
- Execute versus reconcile is covered.
- Provider accepted followed by persistence failure remains ambiguous.

## Failure injection

| Scenario | Final state | Verified |
|---|---|---|
| Crash after reserved | retryAuthorized via reconciliation | Yes |
| Crash after sending | ambiguous via reconciliation | Yes |
| Permanent failure | failedPermanent terminal | Yes |
| Unknown delivery | ambiguous, no automatic retry | Yes |
| Ledger completion failure | sanitized marker in state_root; plan remains verifiable | Yes |
| Snapshot tamper after prepare | approval blocked | Yes |
| Snapshot tamper after approval | execute blocked, zero sends | Yes |

## Privacy

- Logs contain no full email, body, feedback or displayName.
- Ledger stores maskedRecipient, never the normalized/full email.
- The private plan stores normalizedRecipient and binds it into itemHash and previewHash.
- Executor sends only to normalizedRecipient after identity drift verification.
- Recovery markers contain no email, name, body, subject or absolute paths.
- SMTP password is memory-only, omitted from repr/to_dict and never serialized.
- C0 strict scanner passes.

## Batch outcomes

| Outcome | Condition | Verified |
|---|---|---|
| COMPLETE | All recipients sent or idempotently already sent | Yes |
| PARTIAL | Some sent and some failed/blocked | Yes |
| PAUSED | Batch transient notSent with no completed sends | Yes |
| AMBIGUOUS | At least one unknown delivery | Yes |
| BLOCKED | Gate, ledger, lifecycle or configuration prevents sending | Yes |

## Plan bundle verification

`verify_plan_bundle` is the single authority for prepare-existing, inspect, approve and execute. It validates:

- plan and manifest JSON Schemas fail-closed;
- directory basename and manifest planId;
- SHA-256 and size of every declared file;
- itemHash and semantic idempotencyKey;
- previewHash and planId derivation;
- recipient count, ordering and uniqueness;
- exact previews;
- no missing or unexpected files.

## Template registry

- Prepare checks/registers template identity before plan promotion.
- Approve and execute verify the same association.
- Same templateId/version with a different hash fails closed.

## Remote CI

At head `a7bfa2c7230ff5fced74ac56d6364a4da343f7ac`:

- C0 security gates: success
- C1 publication snapshot gates: success
- C2 grade policy engine gates: success
- C3 Email Delivery: success
  - c3-tests: success
  - c3-no-network: success
  - c3-no-secrets: success

## Out of scope

- C4 portal
- C5 teacher/BI
- C6 conventions
- C7 discovery
- HTML email
- Attachments
- CC/BCC
- Multi-recipient messages
- Auto-approval
- `--force`
