# Export and Responsibilities

This page summarizes which file is authoritative at each stage and what each role should check.

## Sources of Truth

| Data | Primary source |
|------|----------------|
| Source data | `evaluations/<SECTION_CODE>/raw/` |
| Full section roster | `evaluations/<SECTION_CODE>/students.json` |
| Effective roster for an EV | `evaluations/<SECTION_CODE>/<EV>/students.json` |
| Forms assigned for an EV | `evaluations/<SECTION_CODE>/<EV>/assignments.json` |
| Grading status | `evaluations/<SECTION_CODE>/<EV>/plan.md` |
| Individual result | `evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md` |
| Normalized export | `exports/publication-input/course/results.json` |

## Export Results

```bash
./scripts/export-results.sh
```

The script reads the graded results and generates the normalized output in:

```text
exports/publication-input/
```

Before exporting, if you changed files in `raw/assignments/`, run `./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan` again.

## Closure Criteria

Before considering an evaluation closed, confirm:

1. Every student in the effective EV roster has an updated status in `plan.md`.
2. Every graded student has a file in `form-x/results/`.
3. The results use the canonical template.
4. `./scripts/export-results.sh` finishes without errors.
5. `exports/publication-input/course/results.json` contains the expected evaluation.
