# AGENTS.md

## Context

- This repository is an academic grading workspace, not a single application.
- The root holds section configuration, templates, scripts, and exports.
- Graded work lives under `evaluations/<SECTION_CODE>/<EV>/`, especially in form folders with `*.psc` files or other evidence defined by the evaluation.

## Read Before Grading

1. `evaluations/<SECTION_CODE>/<EV>/plan.md`
2. `evaluations/<SECTION_CODE>/<EV>/base.md`
3. `evaluations/<SECTION_CODE>/<EV>/form-x/case.md`
4. `engine/templates/result-template.md`

## Standard Layout

```text
<WORKSPACE_ROOT>/
├── docs/                    # Workspace documentation
├── engine/                  # Reusable scripts and templates
├── evaluations/             # Section and evaluation spaces
├── exports/                 # Normalized export + legacy dashboard
└── scripts/                 # Workspace entry points
```

## Operating Rules

- Keep the working state in `evaluations/<SECTION_CODE>/<EV>/plan.md`, not in external notes.
- Use `evaluations/<SECTION_CODE>/students.json` as the base roster and `evaluations/<SECTION_CODE>/<EV>/students.json` as the effective roster for the evaluation.
- Use `evaluations/<SECTION_CODE>/<EV>/assignments.json` for each evaluation’s form assignments; do not consolidate assignments at the section root.
- Keep forms under `evaluations/<SECTION_CODE>/<EV>/form-x/` and keep their official references in `case.md`.
- For new submissions, use `evaluations/<SECTION_CODE>/<EV>/form-x/submissions/`.
- Evidence requirements depend on the evaluation; if submission names are ambiguous, identify exercises by content.
- The rubric style depends on the evaluation; if it is binary, use `Logrado` or `No Logrado`.
- Markdown references must use relative paths.

## Main Scripts

- `./scripts/init-course.sh`
- `./scripts/import-students.sh --csv path.csv`
- `./scripts/add_evaluation.sh`
- `./scripts/prepare-evaluation.sh <EV>`
- `./scripts/assign-forms.sh <EV> --csv path.csv --refresh-plan`
- `./scripts/extract-submissions.sh <EV> --form D`
- `./scripts/review-batch.sh <EV> --form D --limit 3`
- `./scripts/workspace-status.sh`
- `./scripts/export-results.sh`
