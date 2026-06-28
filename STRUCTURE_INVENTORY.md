# Structure Inventory

Inventario del workspace starter. Esta estructura está pensada para comenzar desde cero: no contiene cursos, evaluaciones reales, entregas reales, resultados ni exportes generados.

## Root

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Reglas operativas para el agente dentro del workspace. |
| `AGENTS.es.md` | Versión en español de las reglas operativas, si el docente la prefiere. |
| `README.md` | Entrada principal del workspace starter. |
| `START_HERE.es.md` | Entrada guiada para usuarios que llegan sin contexto. |
| `STRUCTURE_INVENTORY.md` | Este inventario. |
| `.gitignore` | Exclusiones de archivos generados, sesiones locales y configuración privada. |

## `docs/`

| Path | Purpose |
| --- | --- |
| `docs/workspace/README.md` | Índice de documentación operativa del workspace. |
| `docs/workspace/README.es.md` | Índice equivalente en español. |
| `docs/workspace/01-quick-start.md` | Inicio rápido. |
| `docs/workspace/01-quick-start.es.md` | Inicio rápido en español. |
| `docs/workspace/02-overview.md` | Vista general de estructura y responsabilidades. |
| `docs/workspace/02-overview.es.md` | Vista general en español. |
| `docs/workspace/03-course-and-roster.md` | Gestión de curso, sección y roster. |
| `docs/workspace/03-course-and-roster.es.md` | Gestión de curso, sección y roster en español. |
| `docs/workspace/04-evaluations.md` | Estructura y operación de evaluaciones. |
| `docs/workspace/04-evaluations.es.md` | Evaluaciones en español. |
| `docs/workspace/05-grading-flow.md` | Flujo de corrección. |
| `docs/workspace/05-grading-flow.es.md` | Flujo de corrección en español. |
| `docs/workspace/06-export-and-responsibilities.md` | Exportación y responsabilidades de archivos. |
| `docs/workspace/06-export-and-responsibilities.es.md` | Exportación y responsabilidades en español. |
| `docs/workspace/07-full-workflow.md` | Flujo completo de inicio a cierre. |
| `docs/workspace/07-full-workflow.es.md` | Flujo completo en español. |

## `engine/`

| Path | Purpose |
| --- | --- |
| `engine/defaults.json` | Valores por defecto reutilizables. |
| `engine/docs/export-publication.md` | Contrato del export normalizado. |
| `engine/scripts/assign_forms.py` | Aplica asignaciones de forma y roster efectivo por evaluación. |
| `engine/scripts/export-publication-data.py` | Genera datos normalizados de publicación. |
| `engine/scripts/prepare_evaluation.py` | Prepara o refresca estructura operativa de una evaluación. |
| `engine/scripts/review-student.sh` | Utilidad base para revisar una entrega individual. |
| `engine/scripts/students_csv_to_json.py` | Convierte CSV de roster a `students.json`. |
| `engine/scripts/sync-section-indexes.py` | Sincroniza índices de sección y evaluación. |
| `engine/scripts/workspace_status.py` | Diagnostica estado, archivos faltantes, variables e inconsistencias del workspace. |
| `engine/templates/evaluation-base-template.md` | Plantilla fuente para generar `base.md`. |
| `engine/templates/evaluation-case-template.md` | Plantilla fuente para generar `form-x/case.md`. |
| `engine/templates/evaluation-assignments-template.json` | Plantilla fuente para inicializar `assignments.json`. |
| `engine/templates/evaluation-plan-template.md` | Plantilla fuente para generar `plan.md`. |
| `engine/templates/form-assignments-template.csv` | Plantilla CSV para asignar formas. |
| `engine/templates/result-template.md` | Plantilla oficial para resultado individual. |
| `engine/templates/review-plan-template.md` | Plantilla de plan operativo para tandas o revisiones manuales. |
| `engine/templates/sample-result.md` | Ejemplo de resultado. |
| `engine/templates/students-template.csv` | Plantilla CSV de roster. |

## `scripts/`

| Path | Purpose |
| --- | --- |
| `scripts/_common.sh` | Funciones comunes y resolución de `SECTION_CODE`. |
| `scripts/init-course.sh` | Inicializa una nueva sección desde cero. |
| `scripts/import-students.sh` | Importa o reemplaza roster de sección. |
| `scripts/add_evaluation.sh` | Crea una nueva evaluación. |
| `scripts/prepare-evaluation.sh` | Refresca estructura, `base.md`, `case.md` y `plan.md`. |
| `scripts/assign-forms.sh` | Aplica asignaciones de forma desde CSV. |
| `scripts/extract-submissions.sh` | Extrae entregas desde `form-x/submissions/`. |
| `scripts/review-batch.sh` | Revisa estructura de entregas por lote. |
| `scripts/workspace-status.sh` | Reporta estado general del workspace sin modificar archivos. |
| `scripts/export-results.sh` | Exporta resultados normalizados. |

## `automation/`

| Path | Purpose |
| --- | --- |
| `automation/ava/README.md` | Documentación de automatización AVA/Blackboard. |
| `automation/ava/UPGRADE-PLAN.md` | Plan de mejoras de automatización. |
| `automation/ava/ava-import.mjs` | Script de importación/carga AVA. |
| `automation/ava/config.example.json` | Configuración de ejemplo. |
| `automation/ava/package.json` | Dependencias de automatización. |
| `automation/ava/package-lock.json` | Lockfile de dependencias. |

No se incluyen `automation/ava/config.json`, `.ava-session/`, `reports/` ni `node_modules/`.

## `evaluations/`

| Path | Purpose |
| --- | --- |
| `evaluations/.gitkeep` | Mantiene la carpeta vacía en el starter. |

Las secciones reales se crearán después con `./scripts/init-course.sh`:

```text
evaluations/<SECTION_CODE>/
```

## `exports/`

| Path | Purpose |
| --- | --- |
| `exports/.gitkeep` | Mantiene la carpeta base de exportes. |
| `exports/publication-input/.gitkeep` | Mantiene la carpeta donde se generarán exportes normalizados. |

Los JSON de publicación se generan después con `./scripts/export-results.sh`.

## `onboarding/`

| Path | Purpose |
| --- | --- |
| `onboarding/README.md` | Entrada de la simulación guiada. |
| `onboarding/guide.md` | Paso a paso completo de práctica. |
| `onboarding/scripts/build-submission-archives.sh` | Genera ZIPs ficticios de entregas para practicar. |
| `onboarding/data/` | Insumos ficticios para la simulación: roster, evaluación, entregas y resultado de referencia. |

El onboarding no es una evaluación real del workspace; es material de práctica aislado.
