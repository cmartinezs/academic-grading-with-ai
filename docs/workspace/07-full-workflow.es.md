# Algoritmo Completo

Esta guía describe el proceso completo desde la creación de una sección o evaluación hasta la carga de resultados en AVA.

```bash
cd /ruta/al/workspace
```

## Roles

| Responsable | Qué hace |
|-------------|----------|
| Docente | Entrega archivos institucionales, valida criterios pedagógicos y decide casos dudosos. |
| Scripts | Crean estructura, importan datos, extraen submissions, revisan estructura y exportan resultados. |
| Agente IA | Lee submissions, aplica la rúbrica y escribe resultados individuales. |

## Fase 0: Preparar Curso

### Entrada requerida

```text
evaluations/<SECTION_CODE>/raw/roster/students.csv
```

### Comando

```bash
./scripts/import-students.sh --csv evaluations/<SECTION_CODE>/raw/roster/students.csv
```

### Verificación

```text
evaluations/<SECTION_CODE>/students.json
```

## Fase 1: Crear Evaluación

### Comando interactivo

```bash
./scripts/add_evaluation.sh
```

El script pedirá:

| Campo | Ejemplo |
|-------|---------|
| Código | `EV1` |
| Título | `Ejecución práctica` |
| Tipo | `regular` |
| Fecha | `2026-04-15` |
| Ponderación | `25` |
| Formas | `D,E,F` |

### Verificación

```text
evaluations/<SECTION_CODE>/<EV>/
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/students.json
```

## Fase 2: Asignar Formas

### Entrada requerida

```text
evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv
```

### Validar sin modificar

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --dry-run
```

### Aplicar cambios

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

### Verificación

```text
evaluations/<SECTION_CODE>/<EV>/students.json
evaluations/<SECTION_CODE>/<EV>/assignments.json
evaluations/<SECTION_CODE>/<EV>/plan.md
```

El roster efectivo de la evaluación contiene solo los estudiantes incluidos en el CSV de asignación.

## Fase 3: Preparar Material de la Evaluación

### Archivos requeridos

```text
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-d/case.md
evaluations/<SECTION_CODE>/<EV>/form-e/case.md
evaluations/<SECTION_CODE>/<EV>/form-f/case.md
engine/templates/result-template.md
```

La lista de formas puede variar según la metadata de cada evaluación.

## Fase 4: Ingresar Entregas

Descarga desde AVA los archivos originales y cópialos en la carpeta `submissions/` de su forma.

```text
evaluations/<SECTION_CODE>/<EV>/form-d/submissions/
```

## Fase 5: Extraer Entregas

```bash
./scripts/extract-submissions.sh <EV> --form D
```

Si es necesario, filtra por nombre de archivo:

```bash
./scripts/extract-submissions.sh <EV> --form D --match apellido
```

## Fase 6: Revisar Estructura

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
./scripts/review-batch.sh <EV> --form D
```

Este paso valida estructura: presencia de `.psc`, cantidad de archivos, líneas y existencia de resultado. No ejecuta ni compila pseudocódigo.

Los logs quedan en:

```text
evaluations/<SECTION_CODE>/<EV>/support/review-batches/
```

## Fase 7: Corregir

### Antes de corregir

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-d/case.md
engine/templates/result-template.md
```

### Resultado esperado

```text
evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md
evaluations/<SECTION_CODE>/<EV>/plan.md
```

La evidencia principal depende de la evaluación. Si los nombres de archivo son ambiguos, identifica los ejercicios por contenido.

## Fase 8: Exportar Resultados

Antes de exportar, ejecuta el diagnostico del workspace:

```bash
./scripts/workspace-status.sh
```

```bash
./scripts/export-results.sh
```

Salida esperada:

```text
exports/publication-input/course/results.json
```

## Fase 9: Cargar a AVA

La carga a Blackboard se ejecuta desde `automation/ava/` usando Playwright.

```bash
cd automation/ava
npm install
cp config.example.json config.json
```

Inicia sesión manualmente en el navegador abierto por Playwright. La sesión local queda en `automation/ava/.ava-session/`.

```bash
npm run inspect
npm run dry-run -- --student 19452600
npm run import -- --student 19452600
npm run import -- --all
```

Los reportes locales quedan en `automation/ava/reports/`.
