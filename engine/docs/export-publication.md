# Export para workspace de publicación

## Objetivo

Este repo de evaluación produce un output normalizado para que otro workspace o repo se encargue de la publicación. Este workspace representa un solo curso. Aqui no viven frontend, build ni credenciales de acceso.

## Comando

```bash
python3 engine/scripts/export-publication-data.py
```

## Fuentes leidas

1. `evaluations/<SECTION_CODE>/config.json`
2. `evaluations/<SECTION_CODE>/<EV>/plan.md`
3. `evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md`

## Salida

```text
exports/publication-input/
├── manifest.json
└── course/
    ├── course.json
    ├── students.json
    ├── evaluations.json
    ├── results.json
    └── course-summary.json
```

## Manifest

`manifest.json` contiene:

- `generatedAt`
- `schemaVersion`
- `course`

## Payloads por curso

### `course.json`

Metadata del curso y defaults academicos.

### `students.json`

Listado de estudiantes con:

- `id`
- `name`
- `rut`
- `forms`
- `summary`

### `evaluations.json`

Listado de evaluaciones con:

- metadata (`id`, `title`, `type`, `date`, `weight`, `forms`)
- `summary`
- `ieSummary`
- `performanceLevels`

### `results.json`

Resultados por estudiante y evaluación con:

- `studentId`
- `evaluationId`
- `form`
- `status`
- `score`
- `grade`
- `resultPath`
- `finalFeedback`
- `ies`

### `course-summary.json`

Resumen agregado del curso completo.

## Responsabilidades fuera de este repo

El workspace externo de publicación debe resolver por su cuenta:

- autenticación
- passwords o roles de acceso
- frontend y build
- despliegue
- cualquier enriquecimiento visual adicional
