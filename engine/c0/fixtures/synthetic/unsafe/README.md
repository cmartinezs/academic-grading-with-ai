# Unsafe-path scenario (documentation only)

A data root is **unsafe** when it resolves inside the Git worktree and is not fully
ignored. The engine fails closed with `UnsafeDataRootError` and refuses to operate.

Example that must never exist in the repository:

```text
<WORKSPACE_ROOT>/private-data/            # NOT git-ignored  -> unsafe
<WORKSPACE_ROOT>/state/                   # NOT git-ignored  -> unsafe
<WORKSPACE_ROOT>/evaluations/<SEC>/submissions-raw/  # PII under Git -> unsafe
```

Why it is unsafe: any file under these paths can be committed accidentally, leaking
PII (RUT, emails) or secret material (keys, tokens). Migrated private and state data
must live outside the worktree, under the private/state data roots configured in the
runtime configuration.

This directory intentionally contains **no data**. It only documents the boundary.
