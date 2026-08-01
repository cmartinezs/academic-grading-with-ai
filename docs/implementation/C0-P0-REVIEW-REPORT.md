# C0 P0 Review Report — Result: COMPLETE

Branch `feat/c0-security-data-boundaries` · PR #2 (Draft) · 2026-08-01

All P0 review blockers (P0-1..P0-37) for the C0 security/data-boundaries milestone
are resolved and verified. C1–C7 are intentionally not implemented.

## Test suite

```
cd engine && python3 -m unittest discover -s c0/tests -t .
Ran 92 tests in ~1.7s — OK
```

Suites: `test_paths` 20, `test_status` 8, `test_identity` 17, `test_migration` 18,
`test_concurrency` 3, `test_scanner` 26 (incl. staged-blob subprocess tests).

## Commands and results

| Check | Command | Result |
|---|---|---|
| Tracked scan | `./scripts/c0-scan.sh --tracked --strict` | `BLOCK=0 REVIEW=0` (147 files), exit 0 |
| Staged secret gate | `c0_scan.py --staged` on repo with secret staged + clean worktree | `BLOCK=1`, exit 2; worktree `--path` scan `BLOCK=0`, exit 0 |
| Status gate | `./scripts/c0-status.sh` with owner-only runtime roots outside repo | `State: PASS`, exit 0 |
| Migration dry-run | `c0_migrate.py --workspace .` | plan printed, copy nothing, exit 0 |
| Migration apply | `c0_migrate.py --apply --workspace .` | applied, exit 0 |
| Migration reapply | `c0_migrate.py --apply --workspace .` | "already migrated and verified", exit 0 |
| Migration rollback | `c0_migrate.py --rollback CUR0001-001 --workspace .` | removed 3 hash-verified copies + manifest, exit 0 |
| Unsafe root | migrate with roots inside repo | fails closed, exit 2 |
| Pre-commit hook | installed hook runs `c0_scan.py --staged` on every commit | blocked scanner findings observed during commits |

## P0 blocker coverage

- **Scanner (P0-1..9)**: staged blobs read from Git index (`git show :<path>`); emails
  BLOCK outside reserved domains; explicit per-rule allow-list rejects wildcard `*` and
  high-confidence rules; content size (2 MiB) and binary sniff guards; RUT/email paths and
  values masked (`c0/util.py`); private-artifact path rules enforced. Content skipped for
  size/binary reasons now emits a `REVIEW` finding (`uninspected-large`, `uninspected-binary`)
  so "no findings" never implies "fully inspected".
- **Identity/concurrency (P0-10..18)**: global `identity.lock`; batch `ensure_many` atomic;
  reverse index updated on merge; in-batch duplicate detection; corrupted store →
  `IdentityIntegrityError`; concurrency tests 4 workers × 20 entries.
- **Data roots/permissions (P0-19..25)**: owning-repo detection of the root path itself;
  nested/equal roots → `InvalidRuntimeConfigError`; insecure perms FAIL on all four roots;
  second-Git-worktree and tracked/ignored-root tests.
- **Migration (P0-26..33)**: copy-only (never move/delete origin); manifest
  `<private>/sections/<CODE>/migration-manifest.json`; ledger
  `<state>/migrations/<CODE>-migration.json`; locks under `<state>/locks/`; source-drift
  → PARTIAL + re-apply; per-EV evidence dirs; chunked hashing; missing identity blocks
  `MIGRATED`; private files 0o600; rollback removes hash-verified copies by section code.
- **Docs (P0-34..35)**: runbook + threat model aligned to real copy-only/rollback/manifest
  behavior.
- **Gate (P0-36..37)**: `.github/workflows/c0.yml` runs unit suite, strict tracked scan and
  status gate; no Push-Protection-triggering token literals in committed sources (test
  secrets built at runtime; token-shaped fixture files removed).

## Commit history (no rewrite of published commits)

- `779424b` identity/migration concurrency hardening
- `daa0031` data roots/permissions
- `a6bbef6` scanner allow-list, staged blobs, masking
- `9fd448c` docs + CI gate

## Non-blocking backlog

- **Stale locks after abrupt termination** (documented debt, not a merge blocker):
  `FileLock` uses a timeout but has no TTL/owner recovery for lock files left behind by a
  killed process. Remediation is manual for now (see runbook §5) and hardening is deferred
  to the runtime/state effort.

Working tree clean; branch synced with `origin/feat/c0-security-data-boundaries`.
