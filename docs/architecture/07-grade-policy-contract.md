# 07 — Contrato de Grade Policy

## 1. Objetivo

Definir una política de calificación declarativa que sea:

- tipada;
- determinista;
- validable sin ejecutar expresiones arbitrarias;
- versionable;
- auditable;
- extensible mediante operadores registrados;
- independiente de una institución o asignatura concreta.

## 2. Principio

`grade-policy.json` describe **qué operadores aplicar y con qué parámetros**. No contiene
código, expresiones de texto libre ni reglas evaluadas dinámicamente.

El engine mantiene un catálogo cerrado de operadores. Un operador desconocido, una
referencia inválida o una combinación ambigua detienen el pipeline.

## 3. Autoridad

`grade-policy.json` es la única autoridad para:

- escalas;
- ponderaciones;
- tratamiento de faltantes;
- condiciones tipadas;
- bonos;
- reemplazos;
- caps/floors;
- redondeo;
- cálculo final.

`section-config.json` define evaluaciones y metadata, pero no duplica pesos de cálculo.
Los defaults solo inicializan una policy nueva; no se consultan silenciosamente durante
una publicación.

## 4. Estructura propuesta

```json
{
  "schemaVersion": "1.0.0",
  "policyId": "policy_fpy1101_2026_v1",
  "policyVersion": "1.0.0",
  "inputs": {
    "assessments": ["EV1", "EV2", "EV3", "EV4", "PCT", "EvG"]
  },
  "scale": {
    "operator": "piecewiseLinearScale",
    "inputRange": {"min": 0, "max": 100},
    "outputRange": {"min": 1.0, "passing": 4.0, "max": 7.0},
    "passingInput": 60
  },
  "stages": [
    {
      "id": "presentation-score",
      "phase": "aggregation",
      "operator": "weightedAverage",
      "inputs": [
        {"assessmentId": "EV1", "weight": 0.20},
        {"assessmentId": "EV2", "weight": 0.25},
        {"assessmentId": "EV3", "weight": 0.30},
        {"assessmentId": "EV4", "weight": 0.25}
      ],
      "missingPolicy": "minimumOutput"
    },
    {
      "id": "pct-bonus",
      "phase": "adjustment",
      "operator": "additiveBonus",
      "sourceAssessmentId": "PCT",
      "targetStageId": "presentation-score",
      "cap": 100
    },
    {
      "id": "evg-replacement",
      "phase": "adjustment",
      "operator": "replaceLowestInput",
      "sourceAssessmentId": "EvG",
      "targetStageId": "presentation-score",
      "condition": {
        "operator": "levelAtLeast",
        "level": 4
      }
    },
    {
      "id": "final-rounding",
      "phase": "finalization",
      "operator": "round",
      "targetStageId": "presentation-score",
      "mode": "halfUp",
      "scale": 1
    }
  ]
}
```

El ejemplo ilustra forma y restricciones; no fija la semántica final de FPY1101 hasta
aprobar sus fixtures de conformidad.

## 5. Fases

El orden de aplicación no depende del orden accidental del JSON.

| Fase | Propósito |
|---|---|
| `normalization` | normalizar unidades y estados |
| `aggregation` | combinar componentes |
| `adjustment` | aplicar bonus, caps, reemplazos |
| `conversion` | convertir entre escalas |
| `finalization` | redondeo y salida final |

Cada operador declara en qué fases puede ejecutarse. Las dependencias entre stages deben
formar un DAG; los ciclos son inválidos.

## 6. Catálogo inicial de operadores

### `weightedAverage`

- Entradas numéricas y pesos positivos.
- La suma de pesos debe ser 1 dentro de tolerancia explícita.
- Requiere `missingPolicy`.

### `sum`

- Entradas numéricas de igual unidad.
- Puede aplicar cap/floor explícito.

### `piecewiseLinearScale`

- Transforma una escala de entrada en una escala académica.
- Todos los puntos de quiebre son declarados.

### `additiveBonus`

- Declara fuente, target, unidad y cap.
- No puede cambiar silenciosamente de puntos a nota.

### `replaceLowestInput`

- Declara conjunto de candidatos, fuente y condición tipada.
- Los empates siguen una política explícita.

### `cap` / `floor`

- Operan sobre un stage identificado.

### `round`

- Modos permitidos: `halfUp`, `halfEven`, `floor`, `ceil`, `truncate`.
- Declara escala y stage.

### Condiciones V1

- `statusEquals`;
- `levelAtLeast`;
- `assessmentPresent`;
- `assessmentMissing`;
- `scoreAtLeast`;
- `scoreBelow`.

No se permite una cadena como `"level>=4"`.

## 7. Missing policies

Valores iniciales permitidos:

- `fail`;
- `excludeAndRenormalize`;
- `zero`;
- `minimumOutput`;
- `pending`;
- `notApplicable`.

Cada policy debe ser compatible con el operador y quedar visible en el trace de cálculo.

## 8. Trazabilidad

El engine emite por estudiante un trace estructurado:

```json
{
  "policyId": "...",
  "policyVersion": "...",
  "stages": [
    {
      "stageId": "presentation-score",
      "operator": "weightedAverage",
      "inputs": [],
      "output": 78.4,
      "decisions": []
    }
  ]
}
```

El trace permite explicar:

- valores de entrada;
- reglas aplicadas;
- reglas no aplicadas y motivo;
- redondeos;
- caps;
- tratamiento de faltantes;
- resultado final.

## 9. Validación semántica

Además del JSON Schema, deben validarse:

- referencias a assessments/stages existentes;
- unicidad de IDs;
- ausencia de ciclos;
- unidades compatibles;
- pesos válidos;
- operadores permitidos por fase;
- condiciones compatibles;
- cap/floor dentro de escala;
- orden de redondeo;
- conflicto entre ajustes;
- reachability del resultado final.

## 10. Snapshot de policy

Cada Publication Snapshot incluye una copia completa de la policy efectiva y su hash.
No basta con almacenar una ruta o `policyId` mutable.

## 11. Extensión del catálogo

Agregar un operador requiere:

1. ADR o decisión de dominio documentada.
2. Schema de parámetros.
3. Implementación determinista.
4. Trace contract.
5. Casos válidos e inválidos.
6. Pruebas de propiedades e invariantes.
7. Compatibilidad documentada.
8. Versión mínima de engine.

## 12. Estrategia de pruebas

- golden tests con casos reales sanitizados de FPY1101;
- boundary tests de escala;
- missing values;
- empates en reemplazo;
- múltiples ajustes;
- caps/floors;
- orden de redondeo;
- determinismo;
- schemas inválidos;
- referencias inexistentes;
- property tests de rangos e invariantes.

## 13. Criterio de aceptación

Una nueva asignatura dentro del perfil V1 debe poder definir su cálculo usando operadores
existentes y una policy validada, sin modificar el core.
