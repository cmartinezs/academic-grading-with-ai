# Structure Inventory

Inventario del workspace starter. Esta estructura está pensada para comenzar desde cero: no contiene cursos, evaluaciones reales, entregas reales, resultados ni exportes generados.

## Root

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Reglas operativas para el agente dentro del workspace. |
| `AGENTS.es.md` | Versión en español de las reglas operativas. |
| `README.md` | Entrada principal del workspace starter. |
| `START_HERE.es.md` | Entrada guiada para usuarios que llegan sin contexto. |
| `STRUCTURE_INVENTORY.md` | Este inventario. |
| `ANALYSIS_FPY1101_vs_BASE.md` | Análisis histórico; contiene premisas refutadas y no se usa para planificar. |
| `VALIDATED_ANALYSIS_FPY1101_vs_BASE.md` | Línea base validada de gaps reales. |
| `.gitignore` | Exclusiones de secretos, PII, datos académicos privados y artefactos generados. |

## `docs/architecture/`

| Path | Purpose |
| --- | --- |
| `docs/architecture/README.md` | Índice y estado de la arquitectura objetivo. |
| `docs/architecture/01-target-architecture.md` | Arquitectura basada en Publication Snapshots. |
| `docs/architecture/02-data-flow.md` | Flujo de datos, builders y executors. |
| `docs/architecture/03-canonical-vs-derived.md` | Autoridad de datos, snapshots y derivados. |
| `docs/architecture/04-roadmap.md` | Roadmap C0–C7 y gates. |
| `docs/architecture/05-security-and-data-boundaries.md` | Threat model, PII y límites de almacenamiento. |
| `docs/architecture/06-supported-profile-and-extension-points.md` | Perfil soportado V1 y extensiones. |
| `docs/architecture/07-grade-policy-contract.md` | Contrato tipado de grade policy. |
| `docs/architecture/08-migration-strategy.md` | Migración desde las rutas y scripts actuales. |
| `docs/architecture/09-verification-strategy.md` | Estrategia de pruebas y verificación. |
| `docs/architecture/ADRs/README.md` | Índice y gobernanza de ADRs. |
| `docs/architecture/ADRs/ADR-0001.md` a `ADR-0011.md` | Decisiones arquitectónicas propuestas. |

La estructura `runtime/private`, `runtime/publications` y `runtime/state` corresponde al
diseño objetivo y se incorporará mediante el roadmap. No debe asumirse implementada por
la existencia de la documentación.

## `docs/workspace/`

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
| `engine/defaults.json` | Valores por defecto reutilizables del flujo actual. |
| `engine/docs/export-publication.md` | Contrato vigente del export normalizado. |
| `engine/scripts/assign_forms.py` | Aplica asignaciones de forma y roster efectivo por evaluación. |
| `engine/scripts/export-publication-data.py` | Genera datos normalizados de publicación del flujo actual. |
| `engine/scripts/prepare_evaluation.py` | Prepara o refresca estructura operativa de una evaluación. |
| `engine/scripts/review-student.sh` | Utilidad base para revisar una entrega individual. |
| `engine/scripts/students_csv_to_json.py` | Convierte CSV de roster a `students.json`. |
| `engine/scripts/sync-section-indexes.py` | Sincroniza índices de sección y evaluación. |
| `engine/scripts/workspace_status.py` | Diagnostica estado, archivos faltantes, variables e inconsistencias del workspace. |
| `engine/scripts/c0_scan.py` | Scanner PII/secrets del corte C0 (BLOCK/REVIEW). |
| `engine/scripts/c0_status.py` | Estado de raíces de datos y scanner del corte C0. |
| `engine/scripts/publication_snapshot.py` | CLI de snapshots de publicación y lifecycle (C1). |
| `engine/scripts/publication_snapshot_test.py` | Self-check C1: suite unittest + escenario E2E sintético. |
| `engine/c0/` | Módulo C0: raíces de datos, identidad opaca, locking, scanner, status, allowlist. |
| `engine/c0/tests/` | Suite de tests C0 (unittest, stdlib). |
| `engine/publication/` | Módulo C1: schemas, adaptador legacy, manifest/hashes, builder, lifecycle, compat. |
| `engine/publication/schemas/` | Schemas JSON Draft 2020-12 de contratos de snapshot. |
| `engine/publication/tests/` | Suite de tests C1 (119 tests + E2E). |
| `engine/publication/requirements.txt` | Dependencia pinneada: `jsonschema==4.10.3`. |
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
| `scripts/export-results.sh` | Exporta resultados normalizados mediante el flujo actual. |
| `scripts/c0-test.sh` | Ejecuta la suite de tests C0. |
| `scripts/c0-scan.sh` | Ejecuta el scanner PII/secrets C0. |
| `scripts/c0-status.sh` | Ejecuta el chequeo de raíces de datos C0. |
| `scripts/publication-snapshot.sh` | CLI C1 (build/verify/review/approve/status/transition/compatibility [--replace-legacy-aliases]/reconcile/discard) + `test`. |

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

Las secciones reales se crean con `./scripts/init-course.sh`, pero roster, entregas y
resultados reales están excluidos por defecto. El roadmap migrará estos datos a una raíz
privada explícita.

## `exports/`

| Path | Purpose |
| --- | --- |
| `exports/.gitkeep` | Mantiene la carpeta base de exportes. |
| `exports/publication-input/.gitkeep` | Mantiene la carpeta del export vigente. |

Los outputs generados y privados están excluidos. La arquitectura objetivo reemplaza la
ruta global por snapshots aislados mediante `sectionId/publicationId`.

## `docs/implementation/`

| Path | Purpose |
| --- | --- |
| `docs/implementation/C1-IMPLEMENTATION-PLAN.md` | Plan de implementación del corte C1. |
| `docs/implementation/C1-SNAPSHOT-CONTRACT.md` | Contratos exactos de snapshot, ledger, vistas y exit codes. |
| `docs/implementation/C1-RUNBOOKS.md` | Runbooks operativos de C1. |
| `docs/implementation/C1-VERIFICATION-REPORT.md` | Reporte de verificación final de C1. |

## `.github/workflows/`

| Path | Purpose |
| --- | --- |
| `.github/workflows/c0.yml` | Gates C0 en CI: tests, scan estricto, estado de seguridad. |
| `.github/workflows/c1.yml` | Gates C1 en CI: tests/E2E, regresión C0, scan estricto. |

## `onboarding/`

| Path | Purpose |
| --- | --- |
| `onboarding/README.md` | Entrada de la simulación guiada. |
| `onboarding/guide.md` | Paso a paso completo de práctica. |
| `onboarding/scripts/build-submission-archives.sh` | Genera ZIPs ficticios de entregas para practicar. |
| `onboarding/data/` | Insumos ficticios para la simulación: roster, evaluación, entregas y resultado de referencia. |

El onboarding no es una evaluación real del workspace; es material de práctica aislado.
