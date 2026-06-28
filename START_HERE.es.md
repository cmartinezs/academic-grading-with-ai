# Empieza Aquí

Usa esta guía si llegaste al workspace sin contexto y necesitas decidir qué hacer primero.

Este repositorio no es una aplicación única. Es un workspace para preparar evaluaciones, organizar entregas, corregir con apoyo de agente y exportar resultados.

## Camino 1: Quiero practicar sin tocar datos reales

Empieza por la simulación de onboarding:

```text
onboarding/guide.md
```

Ese recorrido crea una sección ficticia, una evaluación, asignaciones, entregas de prueba y resultados esperados. Es la mejor forma de entender el flujo completo antes de usar una sección real.

## Camino 2: Quiero crear una sección real

Desde la raíz del workspace, inicializa la sección con el CSV de estudiantes:

```bash
./scripts/init-course.sh --students-csv path/to/students.csv
```

Después crea la evaluación:

```bash
export SECTION_CODE=<COURSE_CODE>-<SECTION>
./scripts/add_evaluation.sh
```

Luego sigue el flujo completo en:

```text
docs/workspace/07-full-workflow.es.md
```

## Camino 3: Ya tengo una evaluación y quiero corregir entregas

Primero asegúrate de trabajar sobre la sección correcta:

```bash
export SECTION_CODE=<COURSE_CODE>-<SECTION>
```

Revisa el estado de la evaluación:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
```

Copia las entregas descargadas desde AVA en la carpeta de la forma correspondiente:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/submissions/
```

Luego ejecuta:

```bash
./scripts/extract-submissions.sh <EV> --form D
./scripts/review-batch.sh <EV> --form D --limit 3
./scripts/review-batch.sh <EV> --form D
./scripts/workspace-status.sh
```

Cuando la revisión estructural esté correcta, pide al agente que corrija por estudiante o por tanda. Los resultados deben quedar en:

```text
evaluations/<SECTION_CODE>/<EV>/form-x/results/
```

Finalmente exporta:

```bash
./scripts/export-results.sh
```

## Archivos que orientan el trabajo

- `README.md`: resumen general y flujo recomendado.
- `AGENTS.md`: reglas operativas para trabajar con agente.
- `docs/workspace/01-quick-start.es.md`: guía corta de operación.
- `docs/workspace/07-full-workflow.es.md`: procedimiento extremo a extremo.
- `engine/templates/result-template.md`: formato esperado para resultados corregidos.

## Regla práctica

Si no sabes dónde estás en el proceso, abre primero:

```text
evaluations/<SECTION_CODE>/<EV>/plan.md
```

Ese archivo debe reflejar el estado operativo de la evaluación.
