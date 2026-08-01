# C0 Runbooks

Operational procedures for the C0 data boundaries. Read the threat model in
[`C0-THREAT-MODEL.md`](C0-THREAT-MODEL.md) first.

## 0. Quick references

- Scanner: `./scripts/c0-scan.sh [--tracked|--staged|--path <dir>] [--strict]`
- Status: `./scripts/c0-status.sh [--json] [--strict]`
- Identity: `./scripts/c0-identity.sh [--section <CODE>] [--apply]`
- Migration: `./scripts/c0-migrate.sh [--apply|--rollback <SECTION>] [--section <CODE>]`
- Tests: `./scripts/c0-test.sh`
- Pre-commit hook: `./scripts/install-pre-commit-hook.sh --install|--uninstall`

Exit codes: `c0-scan` 2=BLOCK, 1=REVIEW with `--strict`; `c0-status` 2=FAIL, 1=WARN
with `--strict`; 0 otherwise.

## 1. Commit-time scan (pre-commit)

```sh
./scripts/install-pre-commit-hook.sh --install   # once per clone
```

The hook scans **staged** files. A BLOCK finding aborts the commit.

To remove: `./scripts/install-pre-commit-hook.sh --uninstall`.

Manual full scan:

```sh
python3 engine/scripts/c0_scan.py --tracked   # everything tracked in Git
python3 engine/scripts/c0_scan.py --path evaluations
```

Expected clean result: `BLOCK=0 REVIEW=0`.

## 2. Handling a scanner finding

1. Read the finding: `python3 engine/scripts/c0_scan.py --tracked --json`.
2. If it is **real PII/secret data**: stop committing it. Put it under the private or
   state data root and add the path to `.gitignore`. If already committed, remove the
   file from the worktree **and history** (`git rm --cached` + rewrite if necessary),
   then rotate any exposed credentials.
3. If it is a **legitimate exception**: add a versioned entry to
   `engine/c0/allowlist.json` with a justification, then re-run the scan.

Never allow-list real data. Synthetic fixtures live only under
`engine/c0/fixtures/synthetic/**`.

## 3. Migration from legacy layout

Prerequisite: section `config.json` present (e.g. `evaluations/CUR0001-001/config.json`).

```sh
./scripts/c0-migrate.sh                      # dry run: print the plan, copy nothing
./scripts/c0-migrate.sh --apply              # copy private+state data outside the worktree
./scripts/c0-status.sh                       # expect PASS; legacy WARNs gone
```

Effects: `studentId` identities created in the state root; raw submissions and graded
evidence **copied** to the private root; a manifest written in the private root; a
ledger written in the state root. **The origin is never deleted and never moved.**

Where things live after a migration of section `CUR0001-001`:

- Copied data: `<ACADGRAD_PRIVATE_ROOT>/sections/CUR0001-001/...`
- Manifest: `<ACADGRAD_PRIVATE_ROOT>/sections/CUR0001-001/migration-manifest.json`
- Ledger: `<ACADGRAD_STATE_ROOT>/migrations/CUR0001-001-migration.json`
- Locks: `<ACADGRAD_STATE_ROOT>/locks/migrate-CUR0001-001.lock`

Rollback removes only the verified copies recorded in the manifest (hash-checked),
then deletes the manifest:

```sh
./scripts/c0-migrate.sh --rollback CUR0001-001   # removes verified copies
```

## 4. Safe deletion of legacy data

Only after a successful migration (`--apply`), the manifest exists, and `c0-status`
reports the section migrated:

```sh
# remove the migrated section from the worktree and history
git rm -r evaluations/CUR0001-001
git commit -m "chore: remove migrated section data"
```

For sensitive history, rewrite history and coordinate with collaborators before push.

## 5. Restoring a broken identity ledger

The identity ledger lives at `<state>/identity/identity.json` (owner-only). Do **not**
recreate it manually; run the assignment flow:

```sh
./scripts/c0-identity.sh --section CUR0001-001 --apply
```

`c0-status` fails on integrity issues (`identity` check = FAIL) rather than silently
reassigning. Re-run `./scripts/c0-test.sh` after any manual fix.

## 6. Runtime root configuration

Defaults: `$XDG_DATA_HOME/academic-grading-with-ai/{private,state,publications,tmp}`.

Override with environment variables:

```sh
export ACADGRAD_PRIVATE_ROOT=/srv/grading/private
export ACADGRAD_STATE_ROOT=/srv/grading/state
export ACADGRAD_RUNTIME_CONFIG=/etc/grading/runtime.json
```

Every root is validated against the worktree; an unsafe root fails closed.

## 7. Release/CI gate

```sh
./scripts/c0-test.sh && python3 engine/scripts/c0_scan.py --tracked && ./scripts/c0-status.sh
```

All three must exit 0 before a release branch is merged.
