# C3 Email Contract

## 1. Versioning

All schemas carry `schemaVersion` following semver-compatible conventions.
Major version change → fail-closed. Minor → additive.

## 2. Template Schema (V1)

```json
{
  "schemaVersion": "1.0.0",
  "templateId": "result-notification",
  "templateVersion": "1",
  "intent": "result-notification",
  "subject": "Resultados {{sectionId}} — {{publicationId}}",
  "textBody": "Estimado/a {{displayName}},\n\n{{resultsBlock}}\n\nAtentamente",
  "allowedPlaceholders": ["displayName", "sectionId", "publicationId", "resultsBlock"]
}
```

### Constraints

- `schemaVersion`: required, `"1.0.0"`.
- `templateId`: required, non-empty, `^[a-z0-9][a-z0-9-]*[a-z0-9]$`.
- `templateVersion`: required, positive integer string.
- `intent`: required, non-empty, `^[a-z0-9][a-z0-9-]*[a-z0-9]$`.
- `subject`: required, non-empty, no CR/LF.
- `textBody`: required, non-empty.
- `allowedPlaceholders`: required, non-empty array of `^[a-zA-Z][a-zA-Z0-9]*$`.
- All placeholders in `subject` and `textBody` must appear in `allowedPlaceholders`.
- No unknown placeholders allowed.
- No code execution, includes, loops, or expressions.

### Template Identity

```
templateIdentity = templateId + "/" + templateVersion
templateHash     = SHA-256(canonical JSON of template document)
```

First registration: `templateId/version → templateHash` in ledger.
Subsequent: same `templateId/version` with different `templateHash` → **fail closed**.
Content change requires `templateVersion` increment.

### Placeholders V1

| Placeholder | Source | Required |
|---|---|---|
| `displayName` | IdentityStore | Yes |
| `sectionId` | Plan | Yes |
| `publicationId` | Plan | Yes |
| `resultsBlock` | StudentEmailView | Yes |

## 3. Plan Schema (V1)

```json
{
  "schemaVersion": "1.0.0",
  "planId": "eplan_...",
  "sectionId": "sec_...",
  "publicationId": "pub_...",
  "snapshotContentHash": "...",
  "snapshotReviewHash": "...",
  "snapshotMode": "legacy-effective",
  "templateId": "result-notification",
  "templateVersion": "1",
  "templateHash": "...",
  "intent": "result-notification",
  "senderProfileId": "staff-default",
  "fromAddress": "noreply@example.test",
  "replyTo": "docente@example.test",
  "recipientCount": 3,
  "recipients": [
    {
      "studentId": "stu_...",
      "normalizedRecipient": "user@example.test",
      "maskedRecipient": "u***@example.test",
      "identityProjectionHash": "...",
      "subject": "...",
      "textBody": "...",
      "itemHash": "...",
      "idempotencyKey": "..."
    }
  ],
  "previewHash": "...",
  "manifest": {
    "files": {
      "plan.json": {"sha256": "..."},
      "previews/stu_abc123.txt": {"sha256": "..."}
    }
  }
}
```

### Constraints

- `recipients` sorted by `studentId` (lexicographic).
- `recipientCount` must equal `len(recipients)`.
- No two recipients may share the same `normalizedRecipient`.
- No two recipients may share the same `studentId`.
- `previewHash` is computed over the core (excluding `previewHash` itself and `manifest`).
- `planId` = `"eplan_"` + first 24 hex chars of `previewHash`.
- Each `itemHash` = SHA-256(canonical JSON of that recipient's payload).
- Each `idempotencyKey` = SHA-256(sectionId + publicationId + studentId + normalizedRecipient + templateId + templateVersion + intent).
- `identityProjectionHash` = SHA-256(canonical JSON of {studentId, displayName, contact.email} as used in rendering).

### Snapshot Mode

- `"legacy-effective"`: C1 snapshot with `canonical/results.json`.
- `"grade-policy-effective"`: C2 snapshot with `canonical/outcomes.json`.

## 4. Approval Contract

```json
{
  "planId": "eplan_...",
  "previewHash": "...",
  "recipientCount": 3,
  "approvedBy": "staff.opaque",
  "approvedAt": "2026-08-02T12:00:00Z",
  "status": "approved"
}
```

### Constraints

- `previewHash` must match the current plan exactly.
- `recipientCount` must match the current plan exactly.
- `approvedBy` must be non-empty, non-email, sanitized.
- Plan must not be revoked.
- Snapshot must still be in `approved` state.
- `identityProjectionHash` must show no drift.
- Template version/hash must be valid.
- Approval is atomic (single SQLite transaction).
- Changing any byte of the plan invalidates the approval.

## 5. Transport Contract

### Interface

```python
class EmailTransport(ABC):
    @abstractmethod
    def preflight(self, config: TransportConfig) -> None: ...

    @abstractmethod
    def send(self, message: EmailMessage, envelope: Envelope) -> TransportReceipt: ...
```

### TransportReceipt

```python
@dataclass
class TransportReceipt:
    accepted: bool
    provider_message_id: Optional[str]
    client_message_id: str
    response_code: int
    response_class: str  # "accepted" | "permanent-failure" | "transient-failure" | "unknown"
```

### TransportError

```python
class TransportError(Exception):
    scope: str           # "batch" | "recipient"
    retryability: str    # "transient" | "permanent"
    delivery_certainty: str  # "notSent" | "unknown"
    code: str
    sanitized_message: str
```

### SMTP V1

- `smtplib.SMTP` with `starttls()` or implicit TLS.
- Certificate verification enabled.
- One recipient per `send()` call.
- `EmailMessage` from `email.message`.
- Subject and headers protected against CRLF injection.
- `client_message_id` derived deterministically from `idempotencyKey`.
- Password only from `ACADGRAD_SMTP_PASSWORD` env var.
- No password in CLI args, logs, or versioned files.

### Fake Transport

- Completely offline.
- Configurable: success, auth-failure, invalid-recipient, transient, ambiguous.
- Records only hashes/opaque IDs in tests.
- No network in CI.

## 6. StudentEmailView Contract (V1)

### Schema

```json
{
  "schemaVersion": "1.0.0",
  "studentId": "stu_...",
  "sectionId": "sec_...",
  "publicationId": "pub_...",
  "snapshotMode": "legacy-effective",
  "assessments": [
    {
      "assessmentId": "EV1",
      "assessmentLabel": "Evaluación 1",
      "status": "Logrado",
      "score": "5.5",
      "scoreUnit": "grade",
      "grade": "5.5"
    }
  ]
}
```

### C1 Legacy-Effective Mode

Per assessment in `canonical/results.json`:
- `assessmentId`
- `assessmentLabel` (from `canonical/assessments.json`)
- `status`
- `score` (Decimal string, if present)
- `scoreUnit` (from assessments metadata)
- `grade` (Decimal string, if present)

### C2 Grade-Policy-Effective Mode

From `canonical/outcomes.json`:
- `outcomeId`
- `value` (Decimal string)
- `unit`
- `status` (outcome status)
- `resultState`
- `finalizable`

Plus per-assessment observed results from `canonical/results.json`
(pertinent to the outcome).

### Exclusions (never in StudentEmailView)

- traces
- provenance
- evidenceRefs
- data from other students
- cohort statistics
- RUT
- AVA user
- internal components not approved for student viewing

### Ordering

- Assessments in deterministic order (by `assessmentId` lexicographic).
- Decimal values in canonical string representation.
- Locale-independent.
- Timezone-independent.

### Identity Projection

```python
identity_projection = {
    "studentId": student_id,
    "displayName": display_name,
    "contactEmail": contact_email
}
identityProjectionHash = SHA-256(canonical JSON of identity_projection)
```

Drift detection: re-resolve IdentityStore before execute; recompute
`identityProjectionHash`; any change → plan invalidated, require
new preparation and approval.

## 7. Sender Profile Schema (V1)

```json
{
  "schemaVersion": "1.0.0",
  "senderProfileId": "staff-default",
  "fromAddress": "noreply@example.test",
  "replyTo": "docente@example.test"
}
```

### Constraints

- `fromAddress`: valid email, normalized.
- `replyTo`: valid email, normalized, optional.
- `senderProfileId`: non-empty, `^[a-z0-9][a-z0-9-]*[a-z0-9]$`.
- Profile stored in `private_root/email/sender-profiles/<senderProfileId>.json`.
