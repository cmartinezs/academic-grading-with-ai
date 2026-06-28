# Grading Flow

This flow describes how to move from files downloaded from AVA to graded, exportable results.

## 1. Prepare Context

Read or verify these files before grading:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-x/case.md
engine/templates/result-template.md
```

## 2. Copy Original Submissions

Files downloaded from AVA must be placed in:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/submissions/
```

## 3. Extract Submissions

```bash
./scripts/extract-submissions.sh <EV> --form D
```

The script unpacks `.zip` and `.rar` files, creates a folder per student, and flattens unnecessary wrappers.

## 4. Review Structure

Start with a sample:

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
```

Then review the full form:

```bash
./scripts/review-batch.sh <EV> --form D
```

This step validates structure: presence of `.psc`, file count, line count, and existing result files. It does not run or compile pseudocode.

## 5. Grade Each Student

For each submission, identify exercises by content when filenames are ambiguous.

The result must be written to:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md
```

It must use:

```text
engine/templates/result-template.md
```

## 6. Update Tracking

After grading, update:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
```

## 7. Export

```bash
./scripts/export-results.sh
```

Check the output:

```text
exports/publication-input/course/results.json
```
