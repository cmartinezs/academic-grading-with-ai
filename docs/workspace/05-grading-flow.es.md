# Flujo de Corrección

Este flujo describe cómo pasar desde archivos descargados de AVA hasta resultados corregidos y exportables.

## 1. Preparar contexto

Lee o verifica estos archivos antes de corregir:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
evaluations/<SECTION_CODE>/<EV>/base.md
evaluations/<SECTION_CODE>/<EV>/form-x/case.md
engine/templates/result-template.md
```

## 2. Copiar submissions originales

Los archivos descargados desde AVA deben quedar en:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/submissions/
```

## 3. Extraer submissions

```bash
./scripts/extract-submissions.sh <EV> --form D
```

El script descomprime `.zip` y `.rar`, crea una carpeta por alumno y aplana envoltorios innecesarios.

## 4. Revisar estructura

Primero revisa una muestra:

```bash
./scripts/review-batch.sh <EV> --form D --limit 3
```

Luego revisa toda la forma:

```bash
./scripts/review-batch.sh <EV> --form D
```

Este paso valida estructura: presencia de `.psc`, cantidad de archivos, líneas y existencia de resultado. No ejecuta ni compila pseudocódigo.

## 5. Corregir cada estudiante

Para cada entrega, identifica los ejercicios por contenido cuando los nombres de archivo sean ambiguos.

El resultado debe escribirse en:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/results/<studentId>.md
```

Debe usar como base:

```text
engine/templates/result-template.md
```

## 6. Actualizar seguimiento

Después de corregir, actualiza:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
```

## 7. Exportar

```bash
./scripts/export-results.sh
```

Revisa la salida:

```text
exports/publication-input/course/results.json
```
