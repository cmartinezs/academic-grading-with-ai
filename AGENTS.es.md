# AGENTS.md

## Contexto

- Este repositorio es un **workspace de corrección académica**, no una aplicación única.
- La raíz concentra la configuración de cada sección, plantillas, scripts y exportes.
- El trabajo evaluable está dentro de `evaluations/<SECTION_CODE>/<EV>/`, en particular en carpetas por forma con archivos `*.psc` u otra evidencia definida por la evaluación.

## Qué leer antes de corregir

1. `evaluations/<SECTION_CODE>/<EV>/plan.md`
2. `evaluations/<SECTION_CODE>/<EV>/base.md`
3. `evaluations/<SECTION_CODE>/<EV>/forma-x/caso.md`
4. `engine/templates/result-template.md`

## Estructura homologada

```text
<WORKSPACE_ROOT>/
├── docs/                    # Documentación operativa del workspace
├── engine/                  # Scripts y plantillas reutilizables
├── evaluations/             # Espacios por sección y evaluación
├── exports/                 # Export normalizado + dashboard heredado
└── scripts/                 # Puntos de entrada del workspace
```

## Reglas operativas

- Mantén el estado del trabajo en `evaluations/<SECTION_CODE>/<EV>/plan.md`, no en notas externas.
- Usa `evaluations/<SECTION_CODE>/students.json` como roster base y `evaluations/<SECTION_CODE>/<EV>/students.json` como roster efectivo de la evaluación.
- Usa `evaluations/<SECTION_CODE>/<EV>/assignments.json` para las asignaciones de forma de cada evaluación; no consolides asignaciones en la raíz de la sección.
- Conserva las formas en `evaluations/<SECTION_CODE>/<EV>/forma-x/` y deja sus referencias oficiales en `caso.md`.
- Para nuevas entregas, usa `evaluations/<SECTION_CODE>/<EV>/forma-x/entregas/`.
- La evidencia principal depende de la evaluación; si una entrega trae nombres ambiguos, identifica ejercicios por contenido.
- La rúbrica activa depende de la evaluación; si es binaria, usa `Logrado` o `No Logrado`.
- Toda referencia entre archivos Markdown debe usar rutas relativas.

## Scripts principales

- `./scripts/init-course.sh`
- `./scripts/import-students.sh --csv ruta.csv`
- `./scripts/add_evaluation.sh`
- `./scripts/prepare-evaluation.sh <EV>`
- `./scripts/assign-forms.sh <EV> --csv ruta.csv --refresh-plan`
- `./scripts/extract-submissions.sh <EV> --form D`
- `./scripts/review-batch.sh <EV> --form D --limit 3`
- `./scripts/workspace-status.sh`
- `./scripts/export-results.sh`
