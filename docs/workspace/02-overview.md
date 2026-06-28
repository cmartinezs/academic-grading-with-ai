# Overview

This repository is not a single application. It is an academic grading workspace: it organizes section data, submissions, rubrics, results, and exports.

## Main Layers

```text
<WORKSPACE_ROOT>/
├── docs/          # Workspace documentation
├── engine/        # Reusable templates and scripts
├── evaluations/   # Section and evaluation workspaces
├── exports/       # Generated outputs and legacy dashboard
└── scripts/       # Workspace entry points
```

## Where the Graded Work Lives

The main path is:

```text
evaluations/<SECTION_CODE>/
```

Inside that folder you will find the roster, section configuration, and each evaluation (`EV1`, `EV2`, etc.).

## What to Use for Each Task

| Task | Folder or file |
|------|----------------|
| View source data | `evaluations/<SECTION_CODE>/raw/` |
| View the full section roster | `evaluations/<SECTION_CODE>/students.json` |
| View registered evaluations | `evaluations/<SECTION_CODE>/evaluations.json` |
| Review an evaluation | `evaluations/<SECTION_CODE>/<EV>/plan.md` |
| View students who submitted an evaluation | `evaluations/<SECTION_CODE>/<EV>/students.json` |
| View assigned forms for an evaluation | `evaluations/<SECTION_CODE>/<EV>/assignments.json` |
| Copy new submissions | `evaluations/<SECTION_CODE>/<EV>/form-x/submissions/` |
| View graded results | `evaluations/<SECTION_CODE>/<EV>/form-x/results/` |
| Export results | `exports/publication-input/` |

## Practical Rule

If the data came from an external source or helps reconstruct the state, store it under `evaluations/<SECTION_CODE>/raw/`. If it is operational state for an evaluation, it belongs under `evaluations/<SECTION_CODE>/<EV>/`. If it is a template, script, or generated output, it belongs in `engine/`, `scripts/`, or `exports/`.

## Forms Per Evaluation

The available forms come from each evaluation’s metadata.
