# C0 Threat Model

Status: approved (2026-08-01) · Applies to: runtime data, identity and versioned content.

## 1. Data matrix

| Zone | Location | Content | Versioned? | Access |
|------|----------|---------|------------|--------|
| Private | `ACADGRAD_PRIVATE_ROOT` (default `$XDG_DATA_HOME/academic-grading-with-ai/private`) | raw submissions, personal identifiers (RUT, emails, names), graded evidence | **Never** | owner only (0o700), outside worktree |
| State | `ACADGRAD_STATE_ROOT` (default `.../state`) | identity ledger (opaque `studentId`), manifests, lock files, capabilities | **Never** | owner only (0o700), outside worktree |
| Publications | `ACADGRAD_PUBLICATIONS_ROOT` (default `.../publications`) | generated reports free of PII | Never | owner only |
| Runtime config | `ACADGRAD_RUNTIME_CONFIG` / `runtime.json` | root paths, overrides | Optional | owner only |
| Versioned (Git) | worktree | plan.md, base.md, case.md, synthetic fixtures, allow-listed examples | **Yes** | all collaborators |

Fail-closed rule: a data root inside the worktree that is not fully Git-ignored raises
`UnsafeDataRootError` and the engine refuses to run.

## 2. Assets at risk

- A1: student PII (RUT, email, full name) — regulated in Chile (Ley 19.628).
- A2: private keys and tokens (deployment, AVA).
- A3: raw student submissions / graded evidence.
- A4: the identity mapping (`studentId` ↔ person) stored in the state root.
- A5: graded outcome integrity (reports derived from private evidence).

## 3. Actors / threat events

| # | Actor | Scenario | Impact | Mitigation |
|---|-------|----------|--------|------------|
| T1 | Contributor (accidental) | commits `students.json`/submissions with RUTs | PII leak in Git history | scanner gate (`c0-scan`), pre-commit hook, allow-list audit, `.gitignore` rules |
| T2 | Contributor (accidental) | commits `.env`/key/token material | credential leak | secret detection (`BLOCK` severity), strict exit codes |
| T3 | Contributor (accidental) | creates a data root inside the worktree not ignored | private data becomes versionable | `UnsafeDataRootError` fail-closed checks; `c0-status` FAIL gate |
| T4 | Local adversary | reads private/state root with world permissions | PII + identity leak on disk | 0o700 directory enforcement (`c0-status` permission check) |
| T5 | Local adversary | modifies identity ledger without detection | identity substitution | integrity manifest; migration rollback verified by content hash |
| T6 | Contributor (runtime) | leaves legacy private files under `evaluations/` | old PII remains versionable | `pending-migration` WARN + `legacy-compatibility` checks; runbook for safe migration/deletion |
| T7 | Curious repo reader | inspects Git history/exports | residual PII exposure | migration never deletes origin until safe; exports free of PII; `c0-scan --tracked` gate |

## 4. In scope

This model covers C0 boundaries. It does **not** cover network transport, AVA
credentials rotation, or other sections (C1–C7).

## 5. Residual risks

- Synthetic fixtures are allow-listed wholesale under `engine/c0/fixtures/synthetic/**`;
  real data placed there would escape detection.
- Pre-commit hook is optional; a non-installed environment relies on CI/`c0-status`.
- Identity ledger is protected by filesystem permissions, not encryption-at-rest.

## 6. Verification

- `./scripts/c0-test.sh` — unit suites (paths, classification, identity, migration, scanner, status).
- `python3 engine/scripts/c0_scan.py --tracked` — expect `BLOCK=0 REVIEW=0`.
- `./scripts/c0-status.sh` — expect state `PASS` on a migrated, clean workspace.
