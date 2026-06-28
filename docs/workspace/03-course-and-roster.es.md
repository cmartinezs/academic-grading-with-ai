# Curso y Roster

La sección activa del workspace se define por `SECTION_CODE`. Sus archivos maestros están en:

```text
evaluations/<SECTION_CODE>/
```

## Archivos de sección

| Archivo | Uso |
|---------|-----|
| `config.json` | Configuración general de la sección. |
| `students.json` | Roster maestro del curso o sección. |
| `evaluations.json` | Índice normalizado de evaluaciones registradas. |
| `grades.json` | Consolidado de resultados exportados. |

## Roster por evaluación

Cada evaluación tiene su propio roster operativo:

```text
evaluations/<SECTION_CODE>/<EV>/students.json
```

Ese archivo contiene solo los estudiantes que efectivamente rindieron o entregaron esa evaluación.

Las asignaciones de forma también son por evaluación:

```text
evaluations/<SECTION_CODE>/<EV>/assignments.json
```

## Importar alumnos

Los datos de origen de la sección están documentados en `evaluations/<SECTION_CODE>/raw/README.md`.

Cuando recibas un CSV institucional de alumnos, guárdalo primero en:

```text
evaluations/<SECTION_CODE>/raw/roster/students.csv
```

Luego importa:

```bash
./scripts/import-students.sh --csv evaluations/<SECTION_CODE>/raw/roster/students.csv
```

Resultado esperado:

```text
evaluations/<SECTION_CODE>/students.json
```

## Identificadores

Puede existir un identificador interno `REF-###` cuando no hay RUT consolidado. Ese identificador se usa para mantener trazabilidad dentro del workspace y debe conservarse en resultados, planes y exportes.
