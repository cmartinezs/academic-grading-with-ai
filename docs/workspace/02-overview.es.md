# Visión General

Este repositorio no es una aplicación única. Es un workspace de corrección académica: organiza datos de curso, submissions, rúbricas, resultados y exportes.

## Capas principales

```text
<WORKSPACE_ROOT>/
├── docs/          # Documentación operativa
├── engine/        # Plantillas y scripts reutilizables
├── evaluations/   # Trabajo evaluable por sección y evaluación
├── exports/       # Salidas generadas y dashboard heredado
└── scripts/       # Comandos de entrada del workspace
```

## Dónde ocurre el trabajo evaluable

La ruta principal es:

```text
evaluations/<SECTION_CODE>/
```

Dentro de esa carpeta están el roster, la configuración de la sección y cada evaluación (`EV1`, `EV2`, etc.).

## Qué carpeta usar según la tarea

| Tarea | Carpeta o archivo |
|-------|-------------------|
| Ver datos de origen | `evaluations/<SECTION_CODE>/raw/` |
| Ver roster completo de la sección | `evaluations/<SECTION_CODE>/students.json` |
| Ver evaluaciones registradas | `evaluations/<SECTION_CODE>/evaluations.json` |
| Revisar una evaluación | `evaluations/<SECTION_CODE>/<EV>/plan.md` |
| Ver alumnos que rindieron una evaluación | `evaluations/<SECTION_CODE>/<EV>/students.json` |
| Ver formas asignadas en una evaluación | `evaluations/<SECTION_CODE>/<EV>/assignments.json` |
| Copiar submissions nuevas | `evaluations/<SECTION_CODE>/<EV>/form-x/submissions/` |
| Ver resultados corregidos | `evaluations/<SECTION_CODE>/<EV>/form-x/results/` |
| Exportar resultados | `exports/publication-input/` |

## Regla práctica

Si el dato llegó desde una fuente externa o sirve para reconstruir el estado, guárdalo bajo `evaluations/<SECTION_CODE>/raw/`. Si el archivo ya es estado operativo de una evaluación, debe vivir bajo `evaluations/<SECTION_CODE>/<EV>/`. Si es una plantilla, script o salida generada, debe vivir en `engine/`, `scripts/` o `exports/` según corresponda.

## Formas por evaluación

Las formas disponibles se leen desde la metadata de cada evaluación.
