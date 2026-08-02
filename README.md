# Academic Grading Workspace Starter

Workspace base para corrección académica asistida por agente. No incluye cursos, secciones, evaluaciones, entregas ni resultados ya realizados.

Si llegaste sin contexto, empieza por [Empieza Aquí](START_HERE.es.md).

> **Datos reales:** roster, RUT, emails, entregas, feedback, notas y exports privados no
> deben versionarse. Mientras el corte C0 de la arquitectura no esté implementado, verifica
> manualmente el estado de Git antes de cada commit y mantén los datos reales en un entorno
> privado. Consulta [Seguridad y límites de datos](docs/architecture/05-security-and-data-boundaries.md).

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
3. El docente deja temporalmente las entregas descargadas en `evaluations/<SECTION_CODE>/<EV>/form-x/submissions/`, sin versionarlas.
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
# C3: email delivery from approved publication snapshot
./scripts/email-delivery.sh --section <SECTION_CODE> --publication <PUB_ID> prepare
./scripts/email-delivery.sh --section <SECTION_CODE> --publication <PUB_ID> approve --hash <PREVIEW_HASH>
./scripts/email-delivery.sh --section <SECTION_CODE> --publication <PUB_ID> execute
# C1: build a verifiable snapshot of the legacy export and publish it
./scripts/publication-snapshot.sh --section <SECTION_CODE> build --publication <PUB_ID>
./scripts/publication-snapshot.sh --section <SECTION_CODE> reconcile [--publication <PUB_ID>]
./scripts/publication-snapshot.sh --section <SECTION_CODE> compatibility [--update-legacy-aliases] [--replace-legacy-aliases]
```

`SECTION_CODE` selecciona la sección activa cuando existe más de una carpeta en `evaluations/`.

## Documentación

- [Arquitectura objetivo](docs/architecture/README.md)
- [Análisis validado FPY1101 vs base](VALIDATED_ANALYSIS_FPY1101_vs_BASE.md)
- [Workspace docs](docs/workspace/README.md)
- [Empieza aquí](START_HERE.es.md)
- [Operating rules](AGENTS.md)
- [Structure inventory](STRUCTURE_INVENTORY.md)
- [Onboarding simulation](onboarding/guide.md)
- [Export contract](engine/docs/export-publication.md)
- [C1 implementation plan](docs/implementation/C1-IMPLEMENTATION-PLAN.md)
- [C1 snapshot contract](docs/implementation/C1-SNAPSHOT-CONTRACT.md)
- [C1 runbooks](docs/implementation/C1-RUNBOOKS.md)
- [C3 implementation plan](docs/implementation/C3-IMPLEMENTATION-PLAN.md)
- [C3 email contract](docs/implementation/C3-EMAIL-CONTRACT.md)
- [C3 runbooks](docs/implementation/C3-RUNBOOKS.md)
