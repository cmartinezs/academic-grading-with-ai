# C2 — Contrato de Grade Policy Engine

Especifica los contratos tipados del motor de grade policy. Los schemas JSON
(Draft 2020-12) viven en `engine/grade_policy/schemas/`.

## 1. Identidad y versiones

- `policyId`: identificador opaco de policy, `^[A-Za-z0-9._-]{1,64}$`.
- `policyVersion`: SemVer (`major.minor.patch`).
- `engineMinVersion`: SemVer del engine mínimo compatible.
- `schemaVersion` del documento de policy: `"1.0.0"` (contrato C2).
- `engineVersion` del motor `grade_policy`: `0.2.0`.
- `outcomes`/`traces`: `schemaVersion`/`traceSchemaVersion` `"1.1.0"` (aditivo
  sobre 1.0.0; las versiones 1.0.0 se conservan y siguen siendo válidas).

## 2. Documento de policy (`grade-policy.json`)

```json
{
  "schemaVersion": "1.0.0",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "engineMinVersion": "0.1.0",
  "assessments": ["EV1", "EV2", "EV3", "EV4", "PCT", "EvG"],
  "assessmentUnits": {
    "EV1": "percent", "EV2": "percent", "EV3": "percent", "EV4": "percent",
    "PCT": "percent", "EvG": "level"
  },
  "resultStageId": "final-grade",
  "stages": {
    "presentation-score": {
      "id": "presentation-score",
      "phase": "aggregation",
      "operator": "weightedAverage",
      "inputs": [
        {"ref": "EV1", "weight": "0.25"},
        {"ref": "EV2", "weight": "0.25"},
        {"ref": "EV3", "weight": "0.25"},
        {"ref": "EV4", "weight": "0.25"}
      ],
      "params": {},
      "missingPolicy": "fail"
    },
    "evg-replacement": {
      "id": "evg-replacement",
      "phase": "adjustment",
      "operator": "replaceLowestInput",
      "inputs": [],
      "params": {
        "target": "presentation-score",
        "source": "PCT",
        "tiePolicy": "replaceFirst"
      },
      "condition": {"kind": "levelAtLeast", "params": {"ref": "EvG", "level": "4", "levels": ["1","2","3","4","5","6","7"]}},
      "missingPolicy": "fail"
    },
    "final-scale": {
      "id": "final-scale",
      "phase": "conversion",
      "operator": "piecewiseLinearScale",
      "inputs": [{"ref": "evg-replacement"}],
      "params": {
        "outputUnit": "grade",
        "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
        "outsideRange": "clamp"
      },
      "missingPolicy": "fail"
    },
    "final-grade": {
      "id": "final-grade",
      "phase": "finalization",
      "operator": "round",
      "inputs": [{"ref": "final-scale"}],
      "params": {"decimalPlaces": 2, "mode": "halfUp"},
      "missingPolicy": "fail"
    }
  }
}
```

El documento de arriba es el **ejemplo oficial**: debe validar sin modificación,
calcular un outcome final y generar un snapshot C2. El test de paridad lo copia
literalmente desde este documento (extrae el bloque JSON de esta sección) y
verifica validación, cálculo end-to-end y generación de snapshot sin ninguna
transformación.

### Reglas del documento

- `assessments`: assessmentIds referenciables (unicidad; no PII).
- `assessmentUnits` (opcional): declara la unidad por assessment; habilita la
  inferencia estática de unidades y el backfill de `zero`. Valores del catálogo
  cerrado: `percent`, `points`, `grade`, `scalar`, `level`. Una unidad declarada
  que difiera de la unidad en runtime es error tipado (fail-closed).
- `stages[]`: objeto keyed por `id`; cada stage tiene `phase` válida, `operator`
  del catálogo, `inputs` (refs con `weight` opcional), `params` (schema del
  operador), `missingPolicy` compatible con el operador y `condition` opcional
  (`{"kind", "params"}`).
- `resultStageId`: stage existente y alcanzable.
- Sin `eval`, sin `exec`, sin DSL libre, sin `"level>=4"` como texto.
- `additionalProperties: false` en todos los niveles del schema.

## 3. Inputs normalizados (por estudiante)

```json
{
  "subjectId": "stu_01J...",
  "assessmentInputs": {
    "EV1": {"value": "78.4", "unit": "percent", "status": "Evaluada", "present": true},
    "PCT": {"value": "90.0", "unit": "percent", "status": "Evaluada", "present": true},
    "EvG": {"value": "4", "unit": "level", "status": "Evaluada", "present": true},
    "EV2": {"present": false}
  }
}
```

- `present: false` marca ausencia; el engine aplica `missingPolicy` del stage.
- `status` es un string opaco no-PII (se compara literalmente en `statusEquals`).
- Los valores se convierten con `Decimal(str(value))`.

## 4. Estados tipados de stage

El engine resuelve cada stage a un estado tipado (no binario presente/ausente):

| Estado | Significado | `resultState` del outcome |
|---|---|---|
| `value` | el stage produce valor | `finalized` |
| `missing` | un input requerido está ausente y la política lo propaga | depende de la política |
| `pending` | sin input presente; no finalizable (missingPolicy `pending` o `excludeAndRenormalize` con cero presentes) | `pending` |
| `notApplicable` | la operación no aplica (missingPolicy `notApplicable`); no equivale a cero | `notApplicable` |
| `skippedCondition` | la condición del stage no se cumple; el stage no se ejecuta | `pending` (no finalizable) |

- El estado de un stage dependiente se propaga hacia abajo con el motivo
  correspondiente (p. ej. `pending` por `missing`, `pending` por
  `notApplicable` upstream), de modo que el trace es explicable stage a stage.
- Un outcome es `finalizable` solo si todos los stages del camino al
  `resultStageId` están en `value`; si no, `finalizable: false` y el
  `resultState` describe la causa raíz (primer estado no-`value` del camino).

## 5. Unidades

- Catálogo cerrado: `percent`, `points`, `grade`, `scalar`, `level`.
- Un stage homogéneo exige la misma unidad en todos sus inputs presentes; si se
  mezclan unidades conocidas, el validador lo reporta estáticamente y el engine
  lo rechaza en runtime (`UnitMismatchError`).
- La inferencia estática (`propagate_units`) resuelve las unidades en orden
  topológico usando `assessmentUnits` y la regla de unidad del operador. Solo
  reporta hallazgos sobre unidades conocidas estáticamente; las unidades no
  declaradas se resuelven en runtime y nunca se adivinan.
- `zero` rellena con cero en la **unidad esperada del input** (unidad declarada
  del assessment o unidad común inferida); nunca usa una unidad global. En
  `piecewiseLinearScale` (único operador conversor) el cero se crea en la unidad
  del input ref, nunca con `params.outputUnit`, y el check de rango
  (`outsideRange`) se ejecuta **antes** de escalar: `reject` lanza
  `OutOfRangeError` y `clamp` produce el extremo correspondiente.
- `piecewiseLinearScale` es el único operador que convierte de unidad: exige
  `params.outputUnit` explícito (gate semántico; la unidad de salida no se
  adivina).
- `minimumOutput` exige `params.minimum {value, unit}` explícito.
- Unidad declarada en `assessmentUnits` distinta de la unidad de runtime →
  `UnitMismatchError` (fail-closed, no se silencia).

## 6. Operadores V1 y matriz missing-policy × unidades

Soporte de missing policies por operador (matriz exacta; cualquier otra
combinación es error de validación):

| Operador | `fail` | `zero` | `excludeAndRenormalize` | `minimumOutput` | `pending` | `notApplicable` | Unidad de entrada → salida |
|---|---|---|---|---|---|---|---|
| `weightedAverage` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | conserva (inputs homogéneos) |
| `sum` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | conserva |
| `cap` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | conserva |
| `floor` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | conserva |
| `round` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ | conserva |
| `additiveBonus` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ | conserva la del target |
| `replaceLowestInput` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ | conserva la del target |
| `piecewiseLinearScale` | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | `outputUnit` (explícito) |

### `weightedAverage`

- Params: ninguno (schema vacío).
- `inputs`: lista de `{ref, weight}` con pesos positivos y suma 1 (± `1e-9`).
- Todos los inputs presentes deben tener la misma unidad.
- `excludeAndRenormalize`: excluye ausentes y renormaliza los pesos restantes
  (decisión visible en trace: `originalWeight`, `effectiveWeight`,
  `totalBefore`).
- `minimumOutput`: requiere `params.minimum {value, unit}`.
- Cero inputs presentes: con `excludeAndRenormalize` queda `pending`; con `zero`
  produce `0` en la unidad declarada del stage.

### `sum`

- `inputs`: refs; se ignoran weights.
- Misma unidad en todos los presentes.
- Params opcionales: `cap`, `floor` (misma unidad).
- `excludeAndRenormalize` incompatible (rechazado).

### `piecewiseLinearScale`

- `inputs`: exactamente un ref.
- Params: `outputUnit` (obligatorio), `breakpoints[]` (orden creciente de `x`,
  con `y`), y `outsideRange` ∈ {`clamp`, `reject`} (nunca implícito).
- Interpolación lineal determinista entre puntos de quiebre.
- Sin puntos: inválido. `x` duplicado: inválido.

### `additiveBonus`

- Params: `source` (ref), `target` (ref stage), `cap` (opcional, misma unidad
  que target).
- `inputs` vacío.
- Unidades de source y target compatibles (mismas o conversión explícita fuera
  de alcance: `points` sobre `percent` sin conversión → inválido).
- Output = `target + source`, aplicando `cap` si existe (visible en trace).

### `replaceLowestInput`

- Params: `target` (stage `weightedAverage`), `source` (ref), `tiePolicy` ∈
  {`replaceFirst`, `replaceLast`}.
- La condición va en `stage.condition` (ver §7); nunca en `params`.
- Recalcula el promedio ponderado del target con el menor input presente
  reemplazado por el valor de `source`. No reemplaza más de un input.
- Condición falsa → stage `skippedCondition` (`applied: false`, motivo en trace).

#### Restricción del target en V1 (limitación explícita)

En V1, el target de `replaceLowestInput` queda restringido para no ampliar el
contexto de ejecución del operador:

- `target` debe ser un stage `weightedAverage` con `missingPolicy: fail` (o
  ausente, que equivale a `fail`).
- `target` no puede declarar `condition`.
- Al ejecutar, `target` debe estar en `state=value`; el runtime resuelve el
  estado del target antes de leer sus candidatos.
- Todos los candidatos del target deben estar presentes; sus pesos deben ser
  positivos y sumar 1 (regla general de `weightedAverage`).
- Bajo esta restricción, los pesos originales del target **son** los pesos
  efectivos del reemplazo (no hay exclusión ni renormalización).

El validator rechaza un target con `zero`, `excludeAndRenormalize`,
`minimumOutput`, `pending`, `notApplicable` o `condition`. En runtime, un target
que no esté en `state=value` falla cerrado con error tipado antes de leer
candidatos.

### `cap`

- Params: `cap` (valor con unidad del target).
- Output = `min(value, cap)`; la decisión es visible aunque no modifique.

### `floor`

- Params: `floor` (valor con unidad del target).
- Output = `max(value, floor)`; visible.

### `round`

- Params: `decimalPlaces` (int ≥ 0) o `quantum` (string decimal), `mode`.
- Modos: `halfUp`, `halfEven`, `floor`, `ceil`, `truncate`.
- Conserva la unidad. Posición dentro del DAG: `finalization`.

## 7. Condiciones V1

Las condiciones van en `stage.condition` con `{"kind", "params"}`; toda
condición declara su referencia en `params.ref` (assessmentId o stageId). Esa
referencia es una arista de primera clase del DAG: el stage no puede ejecutarse
antes que su fuente, y una ref inexistente o un ciclo se rechazan en validación.

```json
{"kind": "statusEquals", "params": {"ref": "EV1", "status": "Evaluada"}}
{"kind": "levelAtLeast", "params": {"ref": "EvG", "level": "4", "levels": ["1","2","3","4","5","6","7"]}}
{"kind": "assessmentPresent", "params": {"ref": "PCT"}}
{"kind": "assessmentMissing", "params": {"ref": "EV2"}}
{"kind": "scoreAtLeast", "params": {"ref": "EV1", "threshold": {"value": "60", "unit": "percent"}}}
{"kind": "scoreBelow", "params": {"ref": "EV1", "threshold": {"value": "60", "unit": "percent"}}}
```

- Cada condición tiene schema de `params` cerrado (`additionalProperties: false`).
- Devuelven `(bool, reason)`; el reason se registra en el trace.
- Condición no satisfecha → estado `skippedCondition` (`applied: false`).
- `levelAtLeast`/`scoreAtLeast`/`scoreBelow` fallan cerrado si el source está
  ausente.

## 8. Missing policies

| Policy | Semántica |
|---|---|
| `fail` | error tipado si un input requerido está ausente |
| `excludeAndRenormalize` | excluye ausentes y renormaliza pesos (solo weightedAverage) |
| `zero` | el input ausente se trata como cero en la unidad esperada del stage |
| `minimumOutput` | el output usa `params.minimum {value, unit}`; sin mínimo → validación falla |
| `pending` | outcome no finalizable (`resultState: pending`) |
| `notApplicable` | la operación no aplica (`resultState: notApplicable`); no equivale a cero |

La matriz exacta operador × policy es la de la sección 6; un policy fuera de esa
matriz se rechaza en validación semántica (no por JSON Schema).

## 9. Contrato del trace

```json
{
  "traceSchemaVersion": "1.1.0",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "policyHash": "<sha256>",
  "engineVersion": "0.2.0",
  "subjectId": "stu_01J...",
  "resultStageId": "final-grade",
  "stages": [
    {
      "stageId": "presentation-score",
      "phase": "aggregation",
      "operator": "weightedAverage",
      "operatorVersion": "1.0.0",
      "state": "value",
      "applied": true,
      "inputRefs": ["EV1", "EV2", "EV3", "EV4"],
      "normalizedInputs": [
        {"ref": "EV1", "value": "78.4000", "unit": "percent", "state": "value", "reason": null}
      ],
      "missingDecisions": [],
      "conditionDecision": null,
      "valueBefore": null,
      "valueAfter": "78.4000",
      "output": {"value": "78.4000", "unit": "percent"},
      "decisions": ["weights:1.0000000000 within tolerance"],
      "warnings": []
    }
  ]
}
```

- 1.1.0 añade, de forma aditiva, `state` por stage, `missingDecisions`
  estructuradas (con `policy`, `resultingState`, `originalWeight`,
  `effectiveWeight` cuando aplica, `reason`) y `state`/`reason` por input.
- Los valores decimales se serializan con `decimal_str` (canónico, sin
  exponente).
- Una regla no aplicada aparece con `state: "skippedCondition"`,
  `applied: false` y `decisions: ["not applied: ..."]`.
- Prohibido en el trace: RUT, nombre, email, paths privados, evidence content,
  secretos.

## 10. Outcome calculado

```json
{
  "schemaVersion": "1.1.0",
  "outcomeId": "out_01a2...",
  "subjectId": "stu_01J...",
  "resultStageId": "final-grade",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "value": "5.38",
  "unit": "grade",
  "status": "finalized",
  "resultState": "finalized",
  "finalizable": true,
  "traceHash": "<sha256 del trace>"
}
```

- `outcomeId` determinista: `out_` + primeros 16 bytes de
  `sha256(sectionId|subjectId|resultStageId|policyId)`.
- `status`/`resultState`: `finalized` | `pending` | `notApplicable`.
  `skippedCondition` en el resultado se representa como `resultState: pending`
  con `finalizable: false`.
- `finalizable` es `true` solo si el stage de resultado está en `value`.
- No se usa un assessmentId falso para la nota final.

## 11. Schema versioning

- `policy.schema.json` (C2): `schemaVersion` const `1.0.0`.
- `outcomes.schema.json`: const `1.0.0`; `outcomes-1.1.0.schema.json`:
  const `1.1.0` (aditivo: añade `resultState` y `finalizable`).
- `traces.schema.json`: const `1.0.0`; `traces-1.1.0.schema.json`:
  const `1.1.0` (aditivo: estados tipados y `missingDecisions` estructuradas).
- El motor emite `1.1.0` por defecto; el verificador de snapshot selecciona
  schema por `schemaVersion` declarado + `mode`.
- Major desconocida → `SchemaError` (fail-closed). Minor compatible: aditivo.

## 12. Snapshot C2 (`build --grade-policy`)

`canonical/policy.json` (mode `grade-policy-effective`):

```json
{
  "schemaVersion": "1.0.0",
  "policySchemaVersion": "1.0.0",
  "mode": "grade-policy-effective",
  "calculationAuthority": "grade-policy-engine",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "engineVersion": "0.2.0",
  "policyHash": "<sha256>",
  "policy": { "schemaVersion": "1.0.0", "...": "documento completo de policy" }
}
```

- `policyHash` = sha256 de la serialización canónica del documento `policy`.
- `canonical/outcomes.json` (schema `1.1.0`) y `canonical/traces.json` (schema
  `1.1.0`) se añaden a `manifest.files`, `contentHash` y `reviewHash`.
- Un fallo de policy no deja staging parcial.

## 13. Ejemplos inválidos (rechazados por validación)

- Operador desconocido: `{"operator": "magicAverage"}`.
- Condición textual libre: `"when": "level>=4"`.
- Ciclo: `a -> b -> a` (input o condición).
- Self-reference: `{"ref": "a"}` dentro del stage `a`.
- Referencia de condición inexistente (`params.ref` sin resolver).
- Unidad incompatible: `additiveBonus` de `points` sobre `percent` sin
  conversión.
- Mezcla de unidades conocidas en un stage homogéneo.
- `piecewiseLinearScale` sin `params.outputUnit`.
- `minimumOutput` sin `params.minimum {value, unit}`.
- Pesos que no suman 1: `0.1 + 0.1 + 0.1`.
- `cap` con unidad distinta a la del target.
- `excludeAndRenormalize` en `sum`, `round`, `additiveBonus`,
  `replaceLowestInput` o `piecewiseLinearScale`.
- `zero`/`minimumOutput` en `round`, `additiveBonus` o `replaceLowestInput`.
- `replaceLowestInput` con target `weightedAverage` cuyo `missingPolicy` no es
  `fail` (o ausente) o que declara `condition` (limitación V1, ver §6).
- `round` en fase `aggregation`.
- `resultStageId` inexistente o inalcanzable.
- Dependencia de un stage hacia una fase posterior.
- `assessmentId` duplicado o referencia inexistente.
- Campos desconocidos (schema `additionalProperties: false`).
- `engineMinVersion` mayor que la versión del engine instalado.

## 14. Exit codes CLI

- `0` éxito.
- `1` error de uso / estado inválido.
- `2` fallo de gate (schema, semántica, privacidad) — fail-closed.
