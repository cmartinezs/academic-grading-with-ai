# Evaluaciones

Cada evaluación vive dentro de `evaluations/<SECTION_CODE>/` y usa un código como `EV1`, `EV2`, `EV3` o `EV4`.

## Estructura esperada

```text
evaluations/<SECTION_CODE>/<EV>/
├── plan.md
├── base.md
├── rubric.md
├── students.json
├── assignments.json
├── form-d/
│   ├── case.md
│   ├── statement.md
│   ├── submissions/
│   └── results/
├── form-e/
├── form-f/
└── support/
```

## Archivos clave

| Archivo | Uso |
|---------|-----|
| `plan.md` | Estado operativo de la evaluación. |
| `base.md` | Criterios transversales que aplican a toda la evaluación. |
| `rubric.md` | Rúbrica general, cuando existe a nivel de EV. |
| `students.json` | Roster efectivo de la evaluación: solo quienes rindieron o entregaron. |
| `assignments.json` | Formas asignadas para esta evaluación. |
| `form-x/case.md` | Referencia oficial de la forma. |
| `form-x/statement.md` | Enunciado de la forma, si está separado del caso. |
| `form-x/submissions/` | Archivos originales descargados desde AVA. |
| `form-x/results/` | Resultados corregidos por estudiante. |
| `support/` | Logs, material auxiliar y evidencias de proceso. |

## Plantillas de generación

`prepare_evaluation.py` no define el texto base de los Markdown directamente en el código. Los archivos iniciales se renderizan desde:

```text
engine/templates/evaluation-base-template.md
engine/templates/evaluation-case-template.md
engine/templates/evaluation-assignments-template.json
engine/templates/evaluation-plan-template.md
```

El script completa variables como evaluación, curso, formas y filas dinámicas. Si necesitas evolucionar la estructura inicial de `base.md`, `case.md`, `assignments.json` o `plan.md`, modifica primero esas plantillas.

## Crear una evaluación

Para crear una evaluación nueva de forma guiada:

```bash
./scripts/add_evaluation.sh
```

El script solicita código, título, tipo, fecha, ponderación y formas.

## Sincronizar una evaluación existente

```bash
./scripts/prepare-evaluation.sh <EV> --refresh-plan
```

Usa este comando cuando necesites regenerar `plan.md` o asegurar la estructura base.

## Asignar formas

Guarda el CSV normalizado de asignaciones en:

```text
evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv
```

Prueba primero sin modificar archivos:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --dry-run
```

Si el resultado es correcto, aplica y refresca el plan:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

Ese CSV define el roster efectivo de la evaluación. Los estudiantes del roster maestro que no aparezcan en el CSV no quedan en `<EV>/students.json`.

## Antes de corregir

Confirma que existan y estén completos:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-x/case.md
engine/templates/result-template.md
```
