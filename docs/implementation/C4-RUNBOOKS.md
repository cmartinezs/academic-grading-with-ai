# C4 Runbooks

Operational runbooks for the C4 secure student portal. All commands go through
`./scripts/portal.sh`. Exit codes: `0` success, `1` usage/config, `2`
validation/security/approval gate (fail-closed), `3` partial/blocked/operational.

## 1. Prepare

```bash
./scripts/portal.sh prepare \
  --section <sectionId> \
  --publication <publicationId> \
  --profile <path-to-hosting-profile.json>
```

Output: `releaseId`, `releaseHash`, `objectCount`, `planDir`, capabilities.

Requirements:
- The C1 snapshot for `<sectionId>/<publicationId>` must be `approved` and
  immutable (`publication.verify.verify_snapshot(..., immutable=True)`).
- `revoked`/`corrected`/`superseded` snapshots are rejected (terminal).
- The hosting profile must satisfy the mode requirements of the snapshot.

## 2. Inspect

```bash
./scripts/portal.sh inspect \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId>
```

Recomputes the bundle from the plan directory and verifies `releaseHash`.
Inspect does not require an approval and never prints capability keys.

## 3. Approve

```bash
./scripts/portal.sh approve \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId> \
  --actor <opaque-audit-id> \
  --confirm-reviewed
```

The `--confirm-reviewed` flag is mandatory (exit `1` if omitted). Approval
re-checks the snapshot binding, the `releaseHash`, and identity drift. The
approval record is persisted in the portal ledger.

## 4. Publish

```bash
./scripts/portal.sh publish \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId> \
  --publisher local-static \
  --confirm-publish
```

- Publisher must match the portal mode (`local-static` ↔ `static-encrypted`,
  `fake-authenticated` ↔ `authenticated`).
- Re-verifies the snapshot and identity drift immediately before deploying.
- Publish is at-most-once per idempotency key; re-publishing a published
  release returns the existing receipt (idempotent no-op).
- Output includes the durable `receipt` with `releaseHash`, `hostingProfileId`,
  `publisherType`, `objectCount` and the deployment reference.

## 5. Verify

```bash
./scripts/portal.sh verify \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId>
```

Checks bundle integrity, the approval record, and the snapshot state.

## 6. Status

```bash
./scripts/portal.sh status --release <releaseId>
```

Shows `status` plus the full lifecycle event list from the ledger.

## 7. Reconcile (partial publish recovery)

```bash
./scripts/portal.sh reconcile \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId> \
  --actor system.reconcile
```

- If the deployment is complete: promotes `partial → publishing → published`
  and writes the missing receipt.
- If the deployment is incomplete: transitions to `blocked`.
- Exit code `3` when the release ends `blocked`.

A failed publish (disk full, publisher crash) leaves the release `partial`;
reconcile is the recovery path described in the crash model.

## 8. Revoke

```bash
./scripts/portal.sh revoke \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId> \
  --actor <opaque-audit-id> \
  --reason <reason> \
  --confirm-revoke
```

Only allowed from `published`. Removes deployed objects and records a durable
revoke receipt.

## 9. Purge

```bash
./scripts/portal.sh purge \
  --section <sectionId> \
  --publication <publicationId> \
  --release <releaseId> \
  --actor <opaque-audit-id> \
  --confirm-purge
```

Only allowed from `revoked`. Removes any remaining deployment state and records
a purge receipt. Audit records in the ledger are never deleted.

## 10. Ledger Check

```bash
./scripts/portal.sh ledger-check
```

Runs SQLite `PRAGMA integrity_check` and `foreign_key_check`. Exit `3` on any
issue. If integrity fails: stop operations, restore from backup, reconcile,
re-run.

## 11. Test / Self-check

```bash
./scripts/portal.sh test
```

Runs the full C4 pytest suite, the Node WebCrypto ↔ Python AES-GCM interop
tests, and a synthetic CLI E2E (prepare → approve → publish → verify → status →
revoke → purge) in a throwaway workspace. Never touches real data.

## 12. Identity Drift

If publish reports identity drift (`IdentityDriftError`, exit `2`):

1. Fix the `IdentityStore` record (display name / contact email) to match the
   snapshot's `canonical/results.json`.
2. Prepare a new release from the corrected identity store.
3. Approve and publish the new release.

Do not `--force`; drift is intentional fail-closed behavior.

## 13. Crash/Recovery Quick Reference

| Crash point | State | Recovery |
|---|---|---|
| Before plan rename | staging only | re-prepare (idempotent) |
| After plan rename | plan complete | approve or discard |
| After approval, before publish | approved | publish (idempotent) |
| Mid-deployment | `partial` | reconcile → publish or blocked |
| After deployment, before receipt | deployment exists, no receipt | reconcile → receipt |
| After receipt | `published` | terminal for that releaseHash |

## 14. Capability Distribution

Capability URLs (containing the AES-256 key in the URL fragment `#k=...`) are
private secrets. Distribute them out-of-band (e.g., via C3 email delivery using
the capability manifest); never commit them, never log them, never put them in
query strings.

## 15. Retention

- Portal ledger and receipts: never deleted; backup/restore is the operational
  pattern.
- Plan bundles: retained while any ledger record references them.
- Deployments: purge after revoke; the ledger audit trail is permanent.
