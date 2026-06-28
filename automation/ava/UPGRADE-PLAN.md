# Plan de upgrade — Automatizador parametrizado de AVA

## Objetivo

Convertir el automatizador actual en una herramienta reutilizable para cualquier
evaluación de Blackboard Ultra, sin modificar el código por cada EV.

La ejecución debe recibir como parámetros:

1. URL de la evaluación en AVA.
2. Archivo con estudiantes y sus evaluaciones.
3. Perfil con selectores y textos de la interfaz.
4. Niveles de desempeño disponibles en la rúbrica.
5. Políticas de validación, guardado y conversión.

El flujo actual de EV3, que confirmó individualmente feedback y desempeño en
10 de 10 IE, será la referencia funcional.

## Problemas del diseño actual

- La URL y el ID de evaluación están ligados a `config.json`.
- Los resultados se leen desde una ruta fija:
  `exports/publication-input/course/results.json`.
- El roster se lee desde `evaluations/<SECTION_CODE>/students.json`.
- Los selectores de Blackboard están repartidos dentro de
  `ava-import.mjs`.
- Hay textos y expresiones en español incrustados en el código.
- La asociación entre IE exportado y criterio AVA depende principalmente de su
  posición.
- La validación del puntaje supone una rúbrica sobre 100.
- La sesión, los reportes y la configuración están ligados a este workspace.
- `--all` procesa toda la evaluación y no admite una lista explícita o filtro
  por forma.

## Arquitectura propuesta

```text
automation/ava/
├── bin/
│   └── ava-import.mjs             # CLI y coordinación
├── lib/
│   ├── browser.mjs                # sesión y navegador
│   ├── config.mjs                 # carga y validación de parámetros
│   ├── input.mjs                  # lectura del lote
│   ├── selectors.mjs              # resolución de selectores
│   ├── students.mjs               # navegación y selección
│   ├── feedback.mjs               # feedback general
│   ├── rubric.mjs                 # feedback y desempeño por IE
│   ├── verification.mjs           # controles posteriores
│   └── reports.mjs                # reportes y reanudación
├── profiles/
│   └── blackboard-ultra-es.json   # selectores de interfaz
├── examples/
│   ├── job.example.json           # parámetros de una ejecución
│   └── results.example.json       # estudiantes y evaluaciones
├── schemas/
│   ├── job.schema.json
│   ├── profile.schema.json
│   └── results.schema.json
├── reports/
├── ava-import.mjs                 # wrapper compatible temporal
└── README.md
```

## Archivos de entrada

### 1. Job o ejecución

El archivo `job.json` define qué evaluación cargar y cómo hacerlo.

```json
{
  "jobId": "COURSE101-001V-EV1",
  "evaluationId": "EV3",
  "evaluationUrl": "https://campusvirtual.duoc.cl/ultra/...",
  "resultsFile": "../../exports/publication-input/course/results.json",
  "profileFile": "./profiles/blackboard-ultra-es.json",
  "sessionDirectory": ".ava-session",
  "reportsDirectory": "./reports",
  "studentFilter": {
    "ids": [],
    "forms": ["D"],
    "statuses": ["Evaluada"]
  },
  "rubric": {
    "maximumScore": 100,
    "conversionPolicy": "exact",
    "matchCriteriaBy": ["id", "description", "position"],
    "levels": [
      { "id": "excellent", "label": "Muy buen desempeño", "value": 100 },
      { "id": "good", "label": "Buen desempeño", "value": 80 },
      { "id": "acceptable", "label": "Desempeño aceptable", "value": 60 },
      { "id": "incipient", "label": "Desempeño incipiente", "value": 30 },
      { "id": "not-achieved", "label": "Desempeño no logrado", "value": 0 }
    ]
  },
  "execution": {
    "stopOnError": true,
    "verifyAfterSave": true,
    "verifyGeneralFeedbackAfterReload": true,
    "skipExisting": false,
    "windowWidth": 1920,
    "windowHeight": 1080,
    "timeoutMs": 180000
  }
}
```

La URL también podrá sobrescribirse por CLI:

```bash
npm run import -- --job job.json --url "https://..."
```

### 2. Resultados de estudiantes

El automatizador no debe depender del export interno del curso. Aceptará un
contrato autocontenido:

```json
{
  "schemaVersion": 1,
  "evaluation": {
    "id": "EV3",
    "maximumScore": 100
  },
  "students": [
    {
      "id": "21053679",
      "avaName": "CORTES CANALES, VICTOR MANUEL",
      "form": "D",
      "status": "Evaluada",
      "expectedScore": 73,
      "generalFeedback": "Comentario general...",
      "criteria": [
        {
          "id": "2.1.1",
          "description": "Inicializa variables correctamente",
          "weight": 5,
          "performance": {
            "value": 80,
            "label": "Buen desempeño"
          },
          "expectedPoints": 4,
          "feedback": "Comentario específico del IE..."
        }
      ]
    }
  ]
}
```

Se incorporará un adaptador para continuar leyendo el formato actual
`results.json`, pero el núcleo trabajará siempre con este modelo normalizado.

### 3. Perfil de selectores

Los selectores y textos estarán fuera del código:

```json
{
  "profileId": "blackboard-ultra-es",
  "platform": "Blackboard Ultra",
  "locale": "es",
  "selectors": {
    "activeGradingPanel": ".bb-offcanvas-panel.flexible-attempt-grading-panel[aria-hidden='false']",
    "navigationToggle": {
      "role": "button",
      "name": "Panel de navegación"
    },
    "studentList": "div[class*='listContainer']",
    "studentName": "bdi",
    "generalFeedbackToggle": "#overall-feedback-button",
    "generalFeedbackEditor": "#bb-editor-textbox[contenteditable='true']",
    "generalFeedbackSave": "button[data-analytics-id='attemptGrading.page.body.overallFeedback.saveButton']",
    "generalFeedbackEdit": {
      "role": "button",
      "name": "Editar comentarios generales"
    },
    "openRubric": {
      "role": "button",
      "name": "Abrir rúbrica"
    },
    "rubricHeading": "Rúbrica de calificación",
    "criterionSummary": "button.MuiAccordionSummary-root[aria-expanded]",
    "criterionContainerXPath": "ancestor::*[contains(@class,'MuiAccordion-root')][1]",
    "criterionFeedbackEditor": ".ql-editor[contenteditable='true']",
    "criterionFeedbackButtons": [
      "button[title='Agregar comentarios']",
      "button[aria-label^='Agregar comentarios al criterio:']",
      "button[aria-label^='Editar comentarios al criterio:']",
      "button[aria-label^='Edite los comentarios de este criterio:']"
    ]
  },
  "patterns": {
    "criterionWeight": "% de la calificación total",
    "criterionHasComment": "tiene comentario de texto",
    "score": "(\\d+(?:[.,]\\d+)?)\\s*/\\s*(\\d+(?:[.,]\\d+)?)"
  }
}
```

Cada selector admitirá, en orden:

- selector CSS;
- rol y nombre accesible;
- `data-analytics-id`;
- XPath;
- lista de alternativas.

La herramienta probará las alternativas hasta encontrar una única coincidencia
válida.

## CLI propuesta

```bash
# Validar archivos y correspondencia sin abrir AVA
npm run ava -- validate --job job.json

# Inspeccionar interfaz y probar selectores
npm run ava -- inspect --job job.json --student 21053679

# Simulación sin escritura
npm run ava -- dry-run --job job.json --student 21053679

# Carga individual
npm run ava -- import --job job.json --student 21053679

# Carga por forma
npm run ava -- import --job job.json --form D

# Lista explícita
npm run ava -- import --job job.json --students 21053679,19452600

# Todos los seleccionados por el job
npm run ava -- import --job job.json --all

# Reparar solo feedback general
npm run ava -- repair --job job.json --student 21053679 --only general-feedback

# Reparar criterios faltantes sin sobrescribir los correctos
npm run ava -- repair --job job.json --student 21053679 --only missing-criteria

# Verificar sin escribir
npm run ava -- verify --job job.json --form D
```

`import`, `repair` y cualquier acción de escritura exigirán una selección
explícita mediante `--student`, `--students`, `--form` o `--all`.

## Flujo de ejecución

### 1. Validación local

Antes de abrir el navegador:

- validar los tres archivos contra JSON Schema;
- comprobar que cada estudiante tenga nombre AVA;
- comprobar que exista feedback general si es obligatorio;
- comprobar que cada IE tenga ID, desempeño y feedback;
- comprobar que la suma de pesos coincida con el máximo configurado;
- recalcular `expectedPoints`;
- comprobar que la suma de puntos coincida con `expectedScore`;
- comprobar que cada desempeño exista en los niveles configurados;
- rechazar IDs de IE duplicados.

### 2. Descubrimiento de AVA

- abrir la URL parametrizada;
- localizar el panel activo con el perfil;
- expandir navegación;
- localizar al estudiante;
- abrir la rúbrica;
- contar criterios y niveles;
- extraer descripción, peso y posición de cada criterio;
- construir el mapa entre criterios de entrada y criterios AVA.

### 3. Asociación de criterios

Orden de asociación:

1. ID visible o atributo estable, si AVA lo expone.
2. Descripción normalizada.
3. Peso más descripción.
4. Posición, solo como fallback explícitamente permitido.

La ejecución se detendrá si:

- dos IE locales coinciden con un mismo criterio AVA;
- un criterio no tiene correspondencia;
- existen diferencias de cantidad, peso o descripción fuera de tolerancia.

### 4. Escritura

Por estudiante:

1. Seleccionar al estudiante.
2. Guardar feedback general.
3. Confirmar persistencia del feedback general.
4. Abrir la rúbrica.
5. Por cada IE:
   - abrir el criterio;
   - abrir o editar feedback;
   - escribir y verificar el texto;
   - provocar pérdida de foco para activar el autoguardado;
   - seleccionar el desempeño;
   - confirmar comentario y puntaje parcial;
   - cerrar el criterio.
6. Verificar todos los IE.
7. Verificar total.
8. Recargar o reabrir al estudiante.
9. Volver a verificar feedback general, IE y total.

### 5. Reporte y reanudación

Cada reporte tendrá estado por estudiante y por IE:

```json
{
  "jobId": "COURSE101-001V-EV1",
  "studentId": "21053679",
  "status": "verified",
  "generalFeedback": {
    "written": true,
    "verifiedAfterReload": true
  },
  "criteria": [
    {
      "id": "2.1.1",
      "feedbackWritten": true,
      "feedbackVerified": true,
      "performanceSelected": 80,
      "pointsVerified": 4
    }
  ],
  "expectedScore": 73,
  "verifiedScore": 73,
  "published": false
}
```

Una nueva opción `--resume reporte.json` continuará solo los alumnos o IE no
verificados.

## Modos de sobrescritura

El job definirá una política:

- `fail`: detenerse si AVA ya contiene datos distintos.
- `skip`: no modificar campos ya completos.
- `replace`: reemplazar feedback y desempeño.
- `missing-only`: completar únicamente campos faltantes.

El valor predeterminado será `fail`.

## Seguridad

- Nunca pulsar botones de publicación.
- Mantener `commit=false` como valor predeterminado.
- Detectar y bloquear selectores cuyo texto contenga `Publicar`.
- Guardar captura y HTML diagnóstico al fallar.
- Detener la ejecución masiva en el primer error.
- No guardar cookies ni credenciales en archivos de configuración.
- Usar un directorio de sesión configurable y fuera de control de versiones.
- Registrar URL final, estudiante, criterio y acción realizada.

## Migración directa

Durante la migración:

- `ava-import.mjs` leerá el contrato nuevo de sección y job.
- `config.json` se reemplazará por archivos de ejecución explícitos.
- Los reportes usarán el formato nuevo con detalle por alumno e IE.

## Fases de implementación

### Fase 1 — Contratos y validación

- Crear JSON Schemas.
- Crear ejemplos.
- Implementar carga de `job`, resultados y perfil.
- Normalizar el export actual al nuevo contrato.
- Añadir comando `validate`.

**Criterio de término:** EV3 se valida completamente sin abrir AVA.

### Fase 2 — Extracción modular

- Separar navegador, estudiantes, feedback, rúbrica y reportes.
- Reemplazar selectores incrustados por el perfil.
- Reemplazar la CLI actual por la CLI parametrizada.

**Criterio de término:** un alumno ya corregido puede verificarse con el nuevo
motor y produce el mismo resultado.

### Fase 3 — Correspondencia de IE

- Implementar asociación por descripción, peso y posición.
- Eliminar la dependencia principal del índice.
- Soportar cualquier cantidad de IE, incluyendo EV1 con 38 y EV3 con 10.

**Criterio de término:** dry-run correcto sobre una evaluación de 10 IE y otra
con cantidad distinta.

### Fase 4 — Escritura y verificación posterior

- Implementar `import`, `repair` y `verify`.
- Verificar después de recargar al estudiante.
- Añadir detalle por IE al reporte.
- Implementar `missing-only`.

**Criterio de término:** una prueba controlada confirma feedback general,
feedback y desempeño en todos los IE después de recargar.

### Fase 5 — Lotes, filtros y reanudación

- Añadir `--form`, `--students`, `--all` y `--resume`.
- Crear resumen final del lote.
- Generar capturas diagnósticas ante errores.

**Criterio de término:** un lote se puede detener, inspeccionar y reanudar sin
reprocesar estudiantes verificados.

### Fase 6 — Pruebas

- Pruebas unitarias para validación, conversión y asociación de IE.
- Fixtures HTML anonimizados para selectores.
- Pruebas de integración Playwright contra fixtures locales.
- Prueba manual controlada en AVA con un estudiante.

**Criterio de término:** cambios de lógica se validan sin depender siempre de
una sesión real de AVA.

## Criterios de aceptación del upgrade

- Cambiar de evaluación no requiere editar código.
- URL, resultados, selectores y niveles se entregan como parámetros.
- Admite cualquier número de estudiantes e IE.
- Puede filtrar por alumno, lista, forma o evaluación completa.
- Asocia criterios sin depender exclusivamente de la posición.
- Confirma feedback general después de recargar.
- Confirma feedback, desempeño y puntaje en cada IE.
- Confirma el puntaje total configurable.
- Produce un reporte reanudable por alumno e IE.
- Nunca publica notas.
- Opera solo con el contrato nuevo de sección y job.

## Orden recomendado

Implementar primero las fases 1 a 4. Estas concentran el valor principal:
parametrización, independencia de EV y verificación confiable. Los lotes y la
reanudación deben agregarse después de estabilizar la carga individual.
