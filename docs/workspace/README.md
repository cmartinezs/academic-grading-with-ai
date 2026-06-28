# Workspace Documentation

This folder explains how to operate an academic workspace: prepare sections and evaluations, organize submissions, grade results, and export data.

## Reading Order

1. [Quick Start](01-quick-start.md): create, sync, process, grade, and export.
2. [Overview](02-overview.md): what each main folder contains.
3. [Course and Roster](03-course-and-roster.md): section master files.
4. [Evaluations](04-evaluations.md): expected structure for each EV.
5. [Grading Flow](05-grading-flow.md): how to review submissions.
6. [Export and Responsibilities](06-export-and-responsibilities.md): sources of truth and outputs.
7. [Full Workflow](07-full-workflow.md): end-to-end process.

## Shortcuts

- [Create evaluation](04-evaluations.md#create-an-evaluation)
- [Import roster](03-course-and-roster.md#import-students)
- [Assign forms](04-evaluations.md#assign-forms)
- [Source data](../../evaluations/<SECTION_CODE>/raw/README.md)

## Workspace Root

Always work from the repository or workspace root:

```bash
cd /path/to/workspace
```

If more than one section is present, export `SECTION_CODE` before running scripts.
