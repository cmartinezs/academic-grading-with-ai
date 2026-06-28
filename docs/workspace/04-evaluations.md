# Evaluations

Each evaluation lives under `evaluations/<SECTION_CODE>/` and uses a code such as `EV1`, `EV2`, `EV3`, or `EV4`.

## Expected Structure

```text
evaluations/<SECTION_CODE>/<EV>/
├── plan.md
├── base.md
├── rubric.md
├── students.json
├── assignments.json
├── form-d/
│   ├── case.md
│   ├── statement.md
│   ├── submissions/
│   └── results/
├── form-e/
├── form-f/
└── support/
```

## Key Files

| File | Purpose |
|------|---------|
| `plan.md` | Evaluation operational state. |
| `base.md` | Transversal criteria that apply to the whole evaluation. |
| `rubric.md` | General rubric, when defined at EV level. |
| `students.json` | Effective roster for the evaluation: only students who submitted or took it. |
| `assignments.json` | Assigned forms for this evaluation. |
| `form-x/case.md` | Official form reference. |
| `form-x/statement.md` | Form statement, if separated from the case. |
| `form-x/submissions/` | Original files downloaded from AVA. |
| `form-x/results/` | Graded results per student. |
| `support/` | Logs, auxiliary material, and process evidence. |

## Generation Templates

`prepare_evaluation.py` does not define the base Markdown text directly in code. Initial files are rendered from:

```text
engine/templates/evaluation-base-template.md
engine/templates/evaluation-case-template.md
engine/templates/evaluation-assignments-template.json
engine/templates/evaluation-plan-template.md
```

The script fills variables such as evaluation, course, forms, and dynamic rows. If you need to evolve the initial structure of `base.md`, `case.md`, `assignments.json`, or `plan.md`, update those templates first.

## Create an Evaluation

To create a new evaluation interactively:

```bash
./scripts/add_evaluation.sh
```

The script asks for code, title, type, date, weight, and forms.

## Sync an Existing Evaluation

```bash
./scripts/prepare-evaluation.sh <EV> --refresh-plan
```

Use this when you need to regenerate `plan.md` or ensure the base structure exists.

## Assign Forms

Store the normalized assignment CSV in:

```text
evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv
```

First test without writing changes:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --dry-run
```

If the result is correct, apply it and refresh the plan:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

That CSV defines the effective roster for the evaluation. Students in the master roster who are not in the CSV must not appear in `<EV>/students.json`.

## Before Grading

Verify that these files exist and are complete:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-x/case.md
engine/templates/result-template.md
```
