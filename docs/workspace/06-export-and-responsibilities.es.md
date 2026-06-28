# Export y Responsabilidades

Esta página resume qué archivo manda en cada etapa y qué debe revisar cada responsable.

## Fuentes de verdad

| Dato | Fuente principal |
|------|------------------|
| Datos de origen | `evaluations/<SECTION_CODE>/raw/` |
| Roster completo de la sección | `evaluations/<SECTION_CODE>/students.json` |
| Roster efectivo de una EV | `evaluations/<SECTION_CODE>/<EV>/students.json` |
| Asignaciones de una EV | `evaluations/<SECTION_CODE>/<EV>/assignments.json` |
| Estado de corrección | `evaluations/<SECTION_CODE>/<EV>/plan.md` |
| Resultado individual | `evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md` |
| Export normalizado | `exports/publication-input/course/results.json` |

## Exportar resultados

```bash
./scripts/export-results.sh
```

El script lee los resultados corregidos y genera la salida normalizada en:

```text
exports/publication-input/
```

Antes de exportar, si cambiaste archivos en `raw/assignments/`, vuelve a ejecutar `./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan`.

## Criterios de cierre

Antes de considerar cerrada una evaluación, confirma:

1. Cada estudiante del roster efectivo de la EV tiene estado actualizado en `plan.md`.
2. Cada estudiante evaluado tiene archivo en `form-x/results/`.
3. Los resultados usan la plantilla canónica.
4. `./scripts/export-results.sh` termina sin errores.
5. El archivo `exports/publication-input/course/results.json` contiene la evaluación esperada.
