# Review plan {{EVALUATION_ID}}

## Context

- **Course:** {{COURSE_NAME}} — {{COURSE_TITLE}}
- **Evaluation:** {{EVALUATION_ID}} · {{EVALUATION_TITLE}} ({{EVALUATION_WEIGHT}}%)
- **Evaluation roster:** [`students.json`](students.json)
- **Statement and rubric:** [`base.md`](base.md)
- **Available forms:**
{{FORM_LINKS}}
- **Base templates:**
  - Result: [`../../../engine/templates/result-template.md`](../../../engine/templates/result-template.md)
  - Evaluation base: [`../../../engine/templates/evaluation-base-template.md`](../../../engine/templates/evaluation-base-template.md)
  - Form case: [`../../../engine/templates/evaluation-case-template.md`](../../../engine/templates/evaluation-case-template.md)
  - Assignments: [`../../../engine/templates/evaluation-assignments-template.json`](../../../engine/templates/evaluation-assignments-template.json)
  - Generated plan: [`../../../engine/templates/evaluation-plan-template.md`](../../../engine/templates/evaluation-plan-template.md)
  - Review batch plan: [`../../../engine/templates/review-plan-template.md`](../../../engine/templates/review-plan-template.md)

## Review strategy

1. Prepare submissions in `form-x/submissions/` and extract them inside the matching form folder.
2. Keep this EV's `students.json` limited to students who actually submitted or took the evaluation.
3. Read `base.md` and the matching `case.md` before reviewing.
4. Update this plan throughout the evaluation.
5. Generate or maintain the result in `form-x/results/<studentId>.md`, respecting the matching form.

## Review order

{{REVIEW_ORDER}}

### Unassigned

| Order | Student | RUT | Form | Notes |
| ---: | --- | ---: | --- | --- |
{{UNASSIGNED_ROWS}}

## Parallel review

- **Current parallel batch:** to be defined
- **Consistency control:** keep the same criteria, the same structure, and the same teaching tone.

## Action log

| Order | Student | Action taken | Status | Notes |
| ---: | --- | --- | --- | --- |
| 1 | - | Evaluation initialized with base structure | pending | Complete with the first real action. |

## Follow-up

- Record criteria, coordination questions, and adjustments applied during review here.
