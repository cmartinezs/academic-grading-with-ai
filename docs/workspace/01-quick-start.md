# Quick Start

Use this guide when the section already exists and you only need to sync data, process submissions, grade, and export results.

If the evaluation does not exist yet, create the base structure first:

```bash
./scripts/add_evaluation.sh
```

The script asks for code, title, type, date, weight, and forms.

## 1. Confirm Location

Run commands from the workspace root:

```bash
pwd
```

## 2. Sync Data

If the form CSV changed, first sync the effective roster from `raw/assignments/`:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

If you only need to regenerate the structure or the plan:

```bash
./scripts/prepare-evaluation.sh <EV> --refresh-plan
```

Check that these files exist:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/students.json
evaluations/<SECTION_CODE>/<EV>/assignments.json
```

`<EV>/students.json` contains only the students who actually submitted or took that evaluation. The full section roster lives in `evaluations/<SECTION_CODE>/students.json`.

## 3. Copy Submissions

Copy ZIP or RAR files downloaded from AVA into the matching form folder:

```text
evaluations/<SECTION_CODE>/<EV>/form-d/submissions/
```

If the form differs, use the corresponding form folder.

## 4. Extract Submissions

```bash
./scripts/extract-submissions.sh <EV> --form D
```

## 5. Validate Structure

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
```

If the first pass looks correct, run the full batch:

```bash
./scripts/review-batch.sh <EV> --form D
```

## 6. Grade

Use the evaluation code, form, and student or batch. Examples:

```text
Grade <EV> form D student REF-001.
Grade the next pending batch for <EV> form D with a limit of 3.
```

The grade output must be written to:

```text
evaluations/<SECTION_CODE>/<EV>/form-d/results/
```

## 7. Export Results

Before exporting, check the overall status:

```bash
./scripts/workspace-status.sh
```

```bash
./scripts/export-results.sh
```

Main output:

```text
exports/publication-input/course/results.json
```
