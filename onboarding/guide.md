# Onboarding: Simulación Completa

Esta guía reproduce una situación de corrección real con datos ficticios. La idea es practicar el flujo completo sin que la evaluación venga lista desde el inicio.

Ejecuta todo desde la raíz del repositorio. En los ejemplos se usa `<workspace>` como marcador de posición; reemplázalo por la carpeta donde clonaste o guardaste este workspace:

```bash
cd <workspace>
```

Para confirmar que estás en la carpeta correcta, este comando debería mostrar `onboarding`, `scripts` y `evaluations`:

```bash
ls
```

La sección de práctica será `ONB1001-001V`. Cuando ejecutes comandos después de crear la sección, usa siempre:

```bash
export SECTION_CODE=ONB1001-001V
```

## Cómo usar esta guía con el agente

El flujo esperado es conversacional. El docente prepara o descarga los insumos académicos y administrativos; el agente ejecuta los scripts, actualiza archivos operativos y ayuda a iterar la evaluación.

Responsabilidad del docente:

- Descargar la lista de alumnos del curso antes de inicializar la sección.
- Crear o entregar el CSV de asignación de formas.
- Proveer el enunciado de cada forma como `statement.md`.
- Proveer la rúbrica de cada forma como `rubric.md`.
- Descargar las entregas desde AVA y dejarlas en la carpeta de entregas correspondiente.
- Revisar una marcha blanca y entregar ajustes de criterio cuando la corrección no refleje lo esperado.

Responsabilidad del agente:

- Ejecutar los scripts del workspace cuando se le indique.
- Convertir o pulir los enunciados y rúbricas a Markdown profesional sin cambiar el sentido académico.
- Actualizar `base.md` con las reglas transversales de la evaluación.
- Actualizar `case.md` en cada forma con la referencia operativa de esa forma.
- Actualizar `plan.md` cuando cambien asignaciones, materiales o estado de revisión.
- Registrar criterios adicionales en `support/additional-considerations.md` cuando el docente ajuste la interpretación de la rúbrica.
- Evaluar entregas individuales, luego bloques pequeños, usando todo el contexto del workspace.

## 0. Qué vas a construir

Al final deberías tener una sección ficticia en:

```text
evaluations/ONB1001-001V/
```

Dentro se generará una evaluación:

```text
evaluations/ONB1001-001V/EV1/
```

No existe al inicio. La vas a crear con los mismos scripts que se usan en una sección real.

## 1. Inicializar la asignatura

Comando:

```bash
./scripts/init-course.sh --students-csv onboarding/data/01-roster/students.csv
```

Cuando el script pregunte, responde:

```text
Course code           : ONB1001
Title                 : Taller Simulado de Programación
Section               : 001V
Term                  : 2026
```

Por qué se hace:

- Crea la carpeta base de la sección.
- Convierte el CSV de alumnos a `students.json`.
- Deja lista la estructura mínima para registrar evaluaciones.

Resultado esperado:

```text
evaluations/ONB1001-001V/config.json
evaluations/ONB1001-001V/students.json
evaluations/ONB1001-001V/evaluations.json
evaluations/ONB1001-001V/grades.json
```

Verificación rápida:

```bash
python3 -m json.tool evaluations/ONB1001-001V/students.json | head
```

## 2. Activar la sección de práctica

Comando:

```bash
export SECTION_CODE=ONB1001-001V
```

Por qué se hace:

- El repositorio puede tener más de una sección en `evaluations/`.
- Esta variable evita que los scripts operen sobre la sección real.

Verificación:

```bash
echo "$SECTION_CODE"
```

Debe mostrar:

```text
ONB1001-001V
```

## 3. Crear la evaluación

Comando:

```bash
./scripts/add_evaluation.sh
```

Responde:

```text
Código evaluación    : EV1
Título               : Primer control práctico simulado
Tipo                 : regular
Fecha                : 2026-04-15
Ponderación          : 25
Formas               : D,E
```

Por qué se hace:

- Registra la evaluación en la configuración de la sección.
- Crea `EV1/`.
- Crea carpetas `form-d/` y `form-e/`.
- Crea `plan.md`, `base.md`, `students.json` y `assignments.json`.

Resultado esperado:

```text
evaluations/ONB1001-001V/EV1/
├── plan.md
├── base.md
├── students.json
├── assignments.json
├── form-d/
└── form-e/
```

## 4. Preparar el material oficial

En una evaluación real, el docente provee el enunciado y la rúbrica de cada forma. Esos archivos son la fuente académica principal:

```text
form-d/statement.md
form-d/rubric.md
form-e/statement.md
form-e/rubric.md
```

Si el material viene desde Word, PDF, AVA u otra fuente, crea primero los Markdown de cada forma y pídele al agente que los deje claros, consistentes y profesionales. La instrucción típica es:

```text
Deja estos enunciados y rúbricas en formato Markdown profesional, sin cambiar criterios, puntajes ni instrucciones académicas.
```

Para esta práctica, los archivos ya están preparados en `onboarding/data/02-evaluation/EV1/`. Cópialos a la evaluación:

Comandos:

```bash
cp onboarding/data/02-evaluation/EV1/form-d/statement.md evaluations/ONB1001-001V/EV1/form-d/statement.md
cp onboarding/data/02-evaluation/EV1/form-d/rubric.md evaluations/ONB1001-001V/EV1/form-d/rubric.md
cp onboarding/data/02-evaluation/EV1/form-e/statement.md evaluations/ONB1001-001V/EV1/form-e/statement.md
cp onboarding/data/02-evaluation/EV1/form-e/rubric.md evaluations/ONB1001-001V/EV1/form-e/rubric.md
```

Por qué se hace:

- `statement.md` contiene el enunciado oficial de la forma.
- `rubric.md` contiene los criterios oficiales de corrección.
- El agente debe respetar estos archivos como fuente académica.
- `base.md` y `case.md` no reemplazan el enunciado ni la rúbrica; son archivos operativos que el agente debe actualizar después.

Verificación:

```bash
find evaluations/ONB1001-001V/EV1 -maxdepth 2 \( -name 'statement.md' -o -name 'rubric.md' \) -print
```

## 5. Actualizar base, casos y plan

Después de cargar `statement.md` y `rubric.md`, pídele al agente que actualice los archivos operativos de la evaluación:

```text
Actualiza EV1 considerando los statement.md y rubric.md de cada forma.
Actualiza base.md con las reglas transversales, actualiza cada case.md con el resumen operativo de su forma y refresca plan.md.
```

Para esta práctica también existe un `base.md` de referencia. Puedes usarlo como punto de partida:

```bash
cp onboarding/data/02-evaluation/EV1/base.md evaluations/ONB1001-001V/EV1/base.md
./scripts/prepare-evaluation.sh EV1 --refresh-plan
```

Por qué se hace:

- `base.md` concentra reglas comunes: formato esperado, alcance, criterios generales y convenciones de revisión.
- `case.md` resume lo que el agente necesita para corregir cada forma sin mezclar instrucciones entre formas.
- `plan.md` mantiene el estado operativo de la evaluación.

Resultado esperado:

```text
evaluations/ONB1001-001V/EV1/base.md
evaluations/ONB1001-001V/EV1/form-d/case.md
evaluations/ONB1001-001V/EV1/form-e/case.md
evaluations/ONB1001-001V/EV1/plan.md
```

## 6. Asignar formas

Primero valida sin escribir cambios:

```bash
./scripts/assign-forms.sh EV1 --csv onboarding/data/02-evaluation/EV1/form-assignments.csv --dry-run
```

Luego aplica:

```bash
./scripts/assign-forms.sh EV1 --csv onboarding/data/02-evaluation/EV1/form-assignments.csv --refresh-plan
```

Por qué se hace:

- El CSV representa a quienes efectivamente rindieron o entregaron.
- `EV1/students.json` queda como roster efectivo, no como copia completa del curso.
- `EV1/assignments.json` queda con las formas de esta evaluación.

Resultado esperado:

- El curso tiene 6 estudiantes en el roster maestro.
- EV1 queda con 5 estudiantes efectivos.
- Una persona del roster no aparece en EV1 porque no rindió esta actividad.

Verificación:

```bash
python3 - <<'PY'
import json
from pathlib import Path
base = Path("evaluations/ONB1001-001V")
print("course roster:", len(json.loads((base / "students.json").read_text())["students"]))
print("EV1 roster:", len(json.loads((base / "EV1/students.json").read_text())["students"]))
PY
```

Después de aplicar asignaciones, pide al agente que actualice el plan:

```text
Actualiza el plan de EV1 considerando las asignaciones efectivas recién cargadas.
```

## 7. Generar descarga simulada de AVA

Las entregas fuente están como carpetas normales en:

```text
onboarding/data/03-submissions-source/
```

Genera ZIPs simulados:

```bash
./onboarding/scripts/build-submission-archives.sh
```

Resultado esperado:

```text
onboarding/work/ava-downloads/form-d/
onboarding/work/ava-downloads/form-e/
```

Por qué se hace:

- En AVA normalmente se descargan archivos comprimidos.
- Este paso reproduce esa situación sin depender de Blackboard.

## 8. Copiar entregas a la EV

Comandos:

```bash
cp onboarding/work/ava-downloads/form-d/*.zip evaluations/ONB1001-001V/EV1/form-d/submissions/
cp onboarding/work/ava-downloads/form-e/*.zip evaluations/ONB1001-001V/EV1/form-e/submissions/
```

Por qué se hace:

- `form-x/submissions/` guarda la descarga original.
- El extractor trabaja desde esa carpeta.

Verificación:

```bash
find evaluations/ONB1001-001V/EV1/form-d/submissions evaluations/ONB1001-001V/EV1/form-e/submissions -type f
```

## 9. Extraer entregas

Comandos:

```bash
./scripts/extract-submissions.sh EV1 --form D
./scripts/extract-submissions.sh EV1 --form E
```

Por qué se hace:

- Descomprime cada ZIP.
- Crea una carpeta por estudiante dentro de la forma.
- Mantiene intactos los ZIP originales en `submissions/`.

Resultado esperado:

```text
evaluations/ONB1001-001V/EV1/form-d/<submission-folder>/
evaluations/ONB1001-001V/EV1/form-e/<submission-folder>/
```

## 10. Revisar estructura

Primero una muestra:

```bash
./scripts/review-batch.sh EV1 --form D --limit 2
```

Luego todas las entregas:

```bash
./scripts/review-batch.sh EV1 --form D
./scripts/review-batch.sh EV1 --form E
```

Por qué se hace:

- Confirma si hay archivos `*.psc`.
- Detecta entregas incompletas.
- Genera logs en `support/review-batches/`.
- No corrige pedagógicamente.

## 11. Marcha blanca con una entrega

Practica con:

```text
EV1, Form D, student 31001001.
```

Lectura mínima:

```text
evaluations/ONB1001-001V/EV1/plan.md
evaluations/ONB1001-001V/EV1/base.md
evaluations/ONB1001-001V/EV1/form-d/case.md
evaluations/ONB1001-001V/EV1/form-d/statement.md
evaluations/ONB1001-001V/EV1/form-d/rubric.md
engine/templates/result-template.md
```

Instrucción sugerida al agente:

```text
Evalúa la entrega de 31001001 en EV1 forma D como marcha blanca. Usa el enunciado, rúbrica, base, case y plantilla de resultado. No evalúes otros estudiantes todavía.
```

Resultado que debes crear:

```text
evaluations/ONB1001-001V/EV1/form-d/results/31001001.md
```

Si quieres comparar después de intentarlo, usa:

```text
onboarding/data/04-reference-results/EV1/form-d/31001001.md
```

Para desbloquear el export sin escribir el resultado manualmente, puedes copiar el resultado de referencia:

```bash
cp onboarding/data/04-reference-results/EV1/form-d/31001001.md evaluations/ONB1001-001V/EV1/form-d/results/31001001.md
./scripts/prepare-evaluation.sh EV1 --refresh-plan
```

## 12. Registrar ajustes de criterio

Si la marcha blanca no refleja lo que esperas, no modifiques la rúbrica oficial salvo que realmente haya un error en la rúbrica. En su lugar, entrega la aclaración al agente y pídele que la registre como consideración adicional:

```text
Registra esta consideración adicional para EV1: [explica el ajuste]. Debe quedar en support/additional-considerations.md y considerarse en las siguientes correcciones.
```

Por qué se hace:

- La rúbrica oficial se mantiene estable.
- Las aclaraciones posteriores quedan trazables.
- El agente puede usar esas consideraciones en las siguientes evaluaciones sin perder el contexto.

Ubicación esperada:

```text
evaluations/ONB1001-001V/EV1/support/additional-considerations.md
```

Después de registrar ajustes, repite la marcha blanca con otro estudiante o vuelve a evaluar el mismo caso si corresponde.

## 13. Evaluar por bloques

Cuando la marcha blanca esté correcta, avanza en grupos pequeños:

```text
Evalúa EV1 en forma D en bloques de 5 a 6 estudiantes. Usa agentes o procesos separados si corresponde, pero respeta plan.md, base.md, case.md, rubric.md y additional-considerations.md.
```

Por qué se hace:

- Permite revisar calidad antes de corregir todo el curso.
- Reduce el riesgo de repetir un criterio incorrecto en muchas entregas.
- Facilita iterar si aparece un caso no previsto.

Durante la revisión, pide al agente que actualice el estado:

```text
Actualiza plan.md con el avance real de corrección de EV1.
```

## 14. Revisión general e iteración

Cuando ya existan varios resultados, revisa una muestra de archivos en `form-x/results/`. Si detectas un patrón que debe corregirse:

1. Explica la consideración al agente.
2. Pide que la registre en `support/additional-considerations.md`.
3. Pide que identifique resultados potencialmente afectados.
4. Revisa o reevalúa esos casos antes de continuar.

## 15. Exportar resultados

Comando:

```bash
./scripts/export-results.sh
```

Por qué se hace:

- Lee `plan.md` y los archivos en `form-x/results/`.
- Genera JSON normalizado para publicación o carga posterior.

Resultado esperado:

```text
exports/publication-input/course/results.json
```

Verificación:

```bash
python3 -m json.tool exports/publication-input/course/results.json | head -40
```

## 16. Cierre de práctica

Checklist:

1. La sección `ONB1001-001V` existe.
2. EV1 fue creada desde cero.
3. El roster efectivo de EV1 tiene 5 estudiantes.
4. Las entregas ZIP fueron generadas y copiadas a `submissions/`.
5. Las entregas fueron extraídas.
6. `review-batch.sh` generó logs.
7. Existe al menos un resultado en `form-x/results/`.
8. Si hubo ajustes, quedaron registrados en `support/additional-considerations.md`.
9. `plan.md` refleja el avance real.
10. `export-results.sh` termina sin errores.

Para repetir la práctica desde cero, elimina solo la sección ficticia y el trabajo generado:

```bash
rm -rf evaluations/ONB1001-001V onboarding/work
```

No ejecutes comandos de limpieza sobre una sección real del docente.
