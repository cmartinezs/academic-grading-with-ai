# Synthetic C0 fixtures

These fixtures are **completely fictional**. They contain zero real student data.

Rules:

- all email addresses use reserved example domains (`example.test`, `example.com`);
- RUT values are synthetic and do not belong to any real person;
- "secrets" in the `pii/` samples are deliberately fake placeholders used only to
  exercise the scanner;
- identifiers are opaque or clearly fake.

Every path under this directory is allow-listed in
[`engine/c0/allowlist.json`](../allowlist.json). Do not put real data here.

## Contents

- `pii/` — scanner exercise samples (fake `.env`, secrets, emails, RUTs, private key).
- `rosters/` — roster CSVs for `./scripts/import-students.sh`:
  - `roster-sample.csv` — valid fictional roster (8 students);
  - `roster-invalid.csv` — missing required columns to exercise the importer error path.
- `sections/` — section snapshots:
  - `valid/` — well-formed `config.json` + `students.json`;
  - `invalid/` — `config.json` intentionally without `course.name`.
- `identity/` — identity-assignment edge cases:
  - `duplicate-rut.json` — two rows sharing a RUT (must fail);
  - `missing-identifier.json` — rows without any stable identifier (must fail).
- `migration/` — `legacy-section/` snapshot replicating pre-C0 data: a section with
  `students.json` carrying RUTs and a form submission, ready to run `c0-migrate`.
- `unsafe/` — documentation-only description of unsafe data-root layouts.
