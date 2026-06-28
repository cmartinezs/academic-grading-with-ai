# Academic Grading Workspace Starter

Workspace base para corrección académica asistida por agente. No incluye cursos, secciones, evaluaciones, entregas ni resultados ya realizados.

Si llegaste sin contexto, empieza por [Empieza Aquí](START_HERE.es.md).

## Inicio rápido

Desde la raíz del workspace:

```bash
./scripts/init-course.sh --students-csv path/to/students.csv
export SECTION_CODE=<COURSE_CODE>-<SECTION>
./scripts/add_evaluation.sh
```

Después de crear una evaluación:

1. El docente provee `statement.md` y `rubric.md` para cada forma.
2. El agente actualiza `base.md`, cada `case.md` y `plan.md`.
3. El docente deja las entregas descargadas en `evaluations/<SECTION_CODE>/<EV>/form-x/submissions/`.
4. El agente extrae, revisa, ejecuta una marcha blanca y luego corrige por bloques.
5. El agente exporta resultados con `./scripts/export-results.sh`.

## Estructura principal

```text
<WORKSPACE_ROOT>/
├── AGENTS.md
├── README.md
├── STRUCTURE_INVENTORY.md
├── automation/
├── docs/
├── engine/
├── evaluations/
├── exports/
├── onboarding/
└── scripts/
```

## Flujo recomendado

```bash
./scripts/init-course.sh --students-csv path/to/students.csv
./scripts/add_evaluation.sh
./scripts/assign-forms.sh <EV> --csv path/to/form-assignments.csv --refresh-plan
./scripts/extract-submissions.sh <EV> --form D
./scripts/review-batch.sh <EV> --form D --limit 3
./scripts/workspace-status.sh
./scripts/export-results.sh
```

`SECTION_CODE` selecciona la sección activa cuando existe más de una carpeta en `evaluations/`.

## Documentación

- [Workspace docs](docs/workspace/README.md)
- [Empieza aquí](START_HERE.es.md)
- [Operating rules](AGENTS.md)
- [Structure inventory](STRUCTURE_INVENTORY.md)
- [Onboarding simulation](onboarding/guide.md)
- [Export contract](engine/docs/export-publication.md)
