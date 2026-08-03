# C3 Runbooks

## 1. Prepare and Review

```bash
./scripts/email-delivery.sh prepare \
  --section <sectionId> \
  --publication <publicationId> \
  --template engine/email_delivery/templates/result-notification-v1.json \
  --sender-profile engine/email_delivery/templates/sender-profile-default.json \
  --mode legacy-effective
```

Output: `planId`, `previewHash`, `recipientCount`.

Review previews in `private_root/email/plans/<sectionId>/<publicationId>/<planId>/previews/`.

Inspect:
```bash
./scripts/email-delivery.sh inspect \
  --section <sectionId> \
  --publication <publicationId> \
  --plan <planId>
```

## 2. Approve

```bash
./scripts/email-delivery.sh approve \
  --plan <planId> \
  --preview-hash <hash> \
  --recipient-count <n> \
  --actor <opaque-audit-id> \
  --section <sectionId> \
  --publication <publicationId> \
  --confirm-reviewed
```

## 3. Execute with Fake Transport (dry run)

```bash
./scripts/email-delivery.sh execute \
  --plan <planId> \
  --preview-hash <hash> \
  --section <sectionId> \
  --publication <publicationId> \
  --transport fake \
  --confirm-send
```

Requires: `lifecycle_ledger` and `identity_store` are resolved automatically by the CLI. Snapshot must be in `approved` state. Identity drift blocks execution.

## 4. Execute with SMTP

Set environment variables:
- `ACADGRAD_SMTP_HOST`
- `ACADGRAD_SMTP_PORT`
- `ACADGRAD_SMTP_USERNAME`
- `ACADGRAD_SMTP_PASSWORD`
- `ACADGRAD_SMTP_TLS_MODE` (optional: `starttls` or `implicitTls`, default: `starttls`)

`TransportConfig` is the single authority for SMTP parameters. No re-reading from environment during `send`. Password is incorporated in-memory only; `repr=False`; never serialized or logged.

## 5. Resume Paused Batch

If execute returned PAUSED (transient failure with no successful sends):

1. Wait for the transient condition to resolve.
2. Re-run execute with the same planId and previewHash.
3. Already-sent recipients are skipped idempotently.

Batch outcomes:
- **COMPLETE**: All recipients sent successfully.
- **PARTIAL**: Some sent, some failed or blocked.
- **PAUSED**: Transient failure with no successful sends.
- **AMBIGUOUS**: At least one delivery with unknown certainty.
- **BLOCKED**: No sends, all recipients blocked or failed.

## 6. Resolve Ambiguous

```bash
./scripts/email-delivery.sh resolve-ambiguous \
  --plan <planId> \
  --student <studentId> \
  --decision sent|not-sent \
  --actor <opaque-audit-id> \
  --reason <sanitized-reason> \
  --confirm
```

- `sent`: Mark as delivered (provider confirmed).
- `not-sent`: Enable retry (bounce confirmed).

## 7. Incorrect Recipient

If a recipient received email at the wrong address:

1. The email has been sent; there is no rollback.
2. Resolve the identity drift in IdentityStore.
3. Prepare a new plan (new publicationId or new intent).
4. Approve and execute the corrective plan.

## 8. Partially Sent Batch

Status:
```bash
./scripts/email-delivery.sh status --plan <planId>
```

For `failedPermanent` recipients: no automatic retry. Assess individually.
For `failedTransient` recipients: authorize retry via reconciliation.

## 9. Auth Failure

1. Verify SMTP credentials in environment.
2. Rotate credentials if compromised.
3. Re-run execute; already-sent recipients are skipped.

## 10. Snapshot Revoked During Batch

If the snapshot transitions to revoked/corrected/superseded during execution:

- The current recipient may complete its delivery.
- No further recipients are initiated.
- Assess the situation and prepare a new plan if needed.

## 11. Recover SQLite Ledger

```bash
./scripts/email-delivery.sh ledger-check
```

If integrity fails:
1. Stop all email operations.
2. Restore from the latest backup.
3. Run reconcile to fix orphan states.
4. Re-run ledger-check.

## 12. Backup via SQLite Backup API

Backup is performed programmatically:
```python
ledger.backup(backup_path)
```

Schedule regular backups to `state_root/email/backups/`.

## 13. Ledger Loss

If the ledger is lost:
- All delivery records are lost.
- Email sent cannot be determined safely.
- Re-delivery risks duplicates.
- Action: reconcile with provider logs if available, or accept risk and re-execute with new intent/publicationId.

## 14. Rotate SMTP Credentials

1. Generate new credentials.
2. Update environment variables.
3. No code or config files need to change.
4. Old credentials are never stored in the repository.

## 15. Legitimate Re-send with New Content

To re-send with genuinely new content:

- New `publicationId` → new idempotency keys.
- New `templateVersion` → new idempotency keys.
- New `intent` → new idempotency keys.

Do NOT use `--force`.

## 16. Retention and Purge

- Ledger: never deleted; backup/restore is the operational pattern.
- Plan bundles: retained while any delivery record references them.
- Purge requires explicit confirmation and only affects plans with all deliveries in terminal states.
