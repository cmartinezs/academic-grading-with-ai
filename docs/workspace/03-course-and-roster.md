# Course and Roster

The active section is defined by `SECTION_CODE`. Its master files live in:

```text
evaluations/<SECTION_CODE>/
```

## Section Files

| File | Purpose |
|------|---------|
| `config.json` | Section-level configuration. |
| `students.json` | Section-wide roster. |
| `evaluations.json` | Normalized list of registered evaluations. |
| `grades.json` | Consolidated export results. |

## Evaluation Roster

Each evaluation has its own operational roster:

```text
evaluations/<SECTION_CODE>/<EV>/students.json
```

That file contains only the students who actually submitted or took that evaluation.

Forms are also tracked per evaluation:

```text
evaluations/<SECTION_CODE>/<EV>/assignments.json
```

## Import Students

The section source data is documented in `evaluations/<SECTION_CODE>/raw/README.md`.

When you receive an institutional CSV, store it first in:

```text
evaluations/<SECTION_CODE>/raw/roster/students.csv
```

Then import it:

```bash
./scripts/import-students.sh --csv evaluations/<SECTION_CODE>/raw/roster/students.csv
```

Expected result:

```text
evaluations/<SECTION_CODE>/students.json
```

## Identifiers

An internal `REF-###` identifier may exist when there is no consolidated RUT. Keep that identifier for traceability in results, plans, and exports.
