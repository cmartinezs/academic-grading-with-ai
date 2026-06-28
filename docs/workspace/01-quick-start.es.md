# Quick Start

Usa esta guía cuando la sección ya existe y solo necesitas sincronizar datos, procesar submissions, corregir y exportar resultados.

Si todavía no existe la evaluación, crea la estructura base primero:

```bash
./scripts/add_evaluation.sh
```

El script pide código, título, tipo, fecha, ponderación y formas.

## 1. Confirmar ubicación

Ejecuta los comandos desde la raíz del workspace:

```bash
pwd
```

## 2. Sincronizar datos

Si cambió el CSV de formas, sincroniza primero el roster efectivo desde `raw/assignments/`:

```bash
./scripts/assign-forms.sh <EV> --csv evaluations/<SECTION_CODE>/raw/assignments/<EV>-forms.csv --refresh-plan
```

Si solo necesitas regenerar la estructura o el plan:

```bash
./scripts/prepare-evaluation.sh <EV> --refresh-plan
```

Revisa que existan estos archivos:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/students.json
evaluations/<SECTION_CODE>/<EV>/assignments.json
```

`<EV>/students.json` contiene solo estudiantes efectivos de esa evaluación. El roster completo de la sección está en `evaluations/<SECTION_CODE>/students.json`.

## 3. Copiar submissions

Copia los ZIP o RAR descargados desde AVA en la carpeta de la forma correspondiente:

```text
evaluations/<SECTION_CODE>/<EV>/form-d/submissions/
```

Si la forma es otra, cambia `form-d` por la carpeta correspondiente.

## 4. Extraer submissions

```bash
./scripts/extract-submissions.sh <EV> --form D
```

## 5. Validar estructura

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
```

Si la revisión inicial está correcta, ejecuta la tanda completa:

```bash
./scripts/review-batch.sh <EV> --form D
```

## 6. Corregir

Indica la evaluación, la forma y el alumno o tanda. Ejemplos:

```text
Corrige <EV> forma D alumno REF-001.
Corrige la siguiente tanda pendiente de <EV> forma D con límite 3.
```

La corrección debe generar archivos en:

```text
evaluations/<SECTION_CODE>/<EV>/form-d/results/
```

## 7. Exportar resultados

Antes de exportar, revisa el estado general:

```bash
./scripts/workspace-status.sh
```

```bash
./scripts/export-results.sh
```

Salida principal:

```text
exports/publication-input/course/results.json
```
