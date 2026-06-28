# Full Workflow

This guide describes the full process from creating a section or evaluation to loading results into AVA.

```bash
cd /path/to/workspace
```

## Roles

| Role | What it does |
|------|--------------|
| Instructor | Provides official files, validates pedagogical criteria, and decides on ambiguous cases. |
| Scripts | Create structure, import data, extract submissions, review structure, and export results. |
| AI Agent | Reads submissions, applies the rubric, and writes individual results. |

## Phase 0: Prepare Course

### Required input

```text
evaluations/<SECTION_CODE>/raw/roster/students.csv
```

### Command

```bash
./scripts/import-students.sh --csv evaluations/<SECTION_CODE>/raw/roster/students.csv
```

### Verification

```text
evaluations/<SECTION_CODE>/students.json
```

## Phase 1: Create Evaluation

### Interactive command

```bash
./scripts/add_evaluation.sh
```

The script will ask for:

| Field | Example |
|-------|---------|
| Code | `EV1` |
| Title | `Practical Execution` |
| Type | `regular` |
| Date | `2026-04-15` |
| Weight | `25` |
| Forms | `D,E,F` |

### Verification

```text
evaluations/<SECTION_CODE>/<EV>/
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/students.json
```

## Phase 2: Assign Forms

### Required input

```text
evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv
```

### Dry run

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --dry-run
```

### Apply changes

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

### Verification

```text
evaluations/<SECTION_CODE>/<EV>/students.json
evaluations/<SECTION_CODE>/<EV>/assignments.json
evaluations/<SECTION_CODE>/<EV>/plan.md
```

The effective roster contains only the students included in the assignment CSV.

## Phase 3: Prepare Evaluation Material

### Required files

```text
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-d/case.md
evaluations/<SECTION_CODE>/<EV>/form-e/case.md
evaluations/<SECTION_CODE>/<EV>/form-f/case.md
engine/templates/result-template.md
```

The available forms may vary depending on the evaluation metadata.

## Phase 4: Add Submissions

Download the official files from AVA and copy them into the `submissions/` folder of each form.

```text
evaluations/<SECTION_CODE>/<EV>/form-d/submissions/
```

## Phase 5: Extract Submissions

```bash
./scripts/extract-submissions.sh <EV> --form D
```

If needed, filter by filename:

```bash
./scripts/extract-submissions.sh <EV> --form D --match surname
```

## Phase 6: Review Structure

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
./scripts/review-batch.sh <EV> --form D
```

This step validates structure: presence of `.psc`, file count, line count, and result files. It does not run or compile pseudocode.

Logs are stored in:

```text
evaluations/<SECTION_CODE>/<EV>/support/review-batches/
```

## Phase 7: Grade

### Before grading

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-d/case.md
engine/templates/result-template.md
```

### Expected output

```text
evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md
evaluations/<SECTION_CODE>/<EV>/plan.md
```

Evidence requirements depend on the evaluation. If filenames are ambiguous, identify exercises by content.

## Phase 8: Export Results

Before exporting, run the workspace diagnostic:

```bash
./scripts/workspace-status.sh
```

```bash
./scripts/export-results.sh
```

Expected output:

```text
exports/publication-input/course/results.json
```

## Phase 9: Load into AVA

The Blackboard loading flow runs from `automation/ava/` using Playwright.

```bash
cd automation/ava
npm install
cp config.example.json config.json
```

Log in manually in the browser opened by Playwright. The local session is stored in `automation/ava/.ava-session/`.

```bash
npm run inspect
npm run dry-run -- --student 19452600
npm run import -- --student 19452600
npm run import -- --all
```

Local reports are stored in `automation/ava/reports/`.
