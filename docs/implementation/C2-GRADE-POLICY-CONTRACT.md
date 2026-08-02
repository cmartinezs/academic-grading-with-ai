# C2 — Contrato de Grade Policy Engine

Especifica los contratos tipados del motor de grade policy antes de escribirlo.
Los schemas JSON (Draft 2020-12) viven en `engine/grade_policy/schemas/`.

## 1. Identidad y versiones

- `policyId`: identificador opaco de policy, `^[A-Za-z0-9._-]{1,64}$`.
- `policyVersion`: SemVer (`major.minor.patch`).
- `engineMinVersion`: SemVer del engine mínimo compatible.
- `schemaVersion`: `"1.0.0"` (contrato C2).
- `engineVersion` del motor `grade_policy`: `0.1.0`.

## 2. Documento de policy (`grade-policy.json`)

```json
{
  "schemaVersion": "1.0.0",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "engineMinVersion": "0.1.0",
  "inputs": {
    "assessments": ["EV1", "EV2", "EV3", "EV4", "PCT", "EvG"]
  },
  "resultStageId": "final-grade",
  "stages": [
    {
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
    {
      "id": "pct-bonus",
      "phase": "adjustment",
      "operator": "additiveBonus",
      "inputs": [],
      "params": {"source": "PCT", "target": "presentation-score", "cap": "100"},
      "missingPolicy": "notApplicable"
    },
    {
      "id": "evg-replacement",
      "phase": "adjustment",
      "operator": "replaceLowestInput",
      "inputs": [],
      "params": {
        "target": "presentation-score",
        "source": "EvG",
        "condition": {"operator": "levelAtLeast", "source": "EvG", "level": 4},
        "tiePolicy": "replaceFirst"
      },
      "missingPolicy": "fail"
    },
    {
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
    {
      "id": "final-grade",
      "phase": "finalization",
      "operator": "round",
      "inputs": [{"ref": "final-scale"}],
      "params": {"decimalPlaces": 2, "mode": "halfUp"},
      "missingPolicy": "fail"
    }
  ]
}
```

### Reglas del documento

- `inputs.assessments`: assessmentIds referenciables (unicidad; no PII).
- `stages[]`: cada stage tiene `id` único, `phase` válida, `operator` del catálogo,
  `inputs` (lista de refs con `weight` opcional), `params` (schema del operador) y
  `missingPolicy` compatible con el operador.
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

## 4. Operadores V1

### `weightedAverage`

- Params: ninguno (schema vacío).
- `inputs`: lista de `{ref, weight}` con pesos positivos y suma 1 (± `1e-9`).
- Todos los inputs presentes deben tener la misma unidad.
- `missingPolicy` requerido.
- `excludeAndRenormalize`: excluye ausentes y renormula los pesos restantes.
- `minimumOutput`: requiere `params.minimum` (valor con unidad).
- Cero inputs presentes: sigue `missingPolicy`.

### `sum`

- `inputs`: refs; se ignoran weights.
- Misma unidad en todos los presentes.
- Params opcionales: `cap`, `floor` (misma unidad).
- `excludeAndRenormalize` incompatible.

### `piecewiseLinearScale`

- `inputs`: exactamente un ref.
- Params: `outputUnit`, `breakpoints[]` (orden creciente de `x`, con `y`), y
  `outsideRange` ∈ {`clamp`, `reject`} (nunca implícito).
- Interpolación lineal determinista entre puntos de quiebre.
- Sin puntos: inválido. `x` duplicado: inválido.

### `additiveBonus`

- Params: `source` (ref), `target` (ref stage), `cap` (opcional, misma unidad que target).
- `inputs` vacío.
- Unidades de source y target compatibles (mismas o conversión explícita fuera de
  alcance: `points` sobre `percent` sin conversión → inválido).
- Output = `target + source`, aplicando `cap` si existe (visible en trace).

### `replaceLowestInput`

- Params: `target` (stage `weightedAverage`), `source` (ref), `condition` (obligatoria),
  `tiePolicy` ∈ {`replaceFirst`, `replaceLast`}.
- Recalcula el promedio ponderado del target con el menor input presente reemplazado
  por el valor de `source`. No reemplaza más de un input.
- Condición falsa → stage `applied: false` (motivo en trace).

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

## 5. Condiciones V1

```json
{"operator": "statusEquals", "source": "EV1", "status": "Evaluada"}
{"operator": "levelAtLeast", "source": "EvG", "level": 4}
{"operator": "assessmentPresent", "source": "PCT"}
{"operator": "assessmentMissing", "source": "EV2"}
{"operator": "scoreAtLeast", "source": "EV1", "threshold": "60"}
{"operator": "scoreBelow", "source": "EV1", "threshold": "60"}
```

- Cada condición declara su `source` (assessmentId o stageId) y su schema cerrado.
- Devuelven `(bool, reason)`; el reason se registra en el trace.
- `levelAtLeast`/`scoreAtLeast`/`scoreBelow` fallan cerrado si el source está ausente.

## 6. Missing policies

| Policy | Semántica |
|---|---|
| `fail` | error tipado si un input requerido está ausente |
| `excludeAndRenormalize` | excluye ausentes y renormaliza pesos (solo weightedAverage) |
| `zero` | el input ausente se trata como cero |
| `minimumOutput` | el output usa `params.minimum`; sin mínimo → validación falla |
| `pending` | outcome no finalizable (`status: pending`) |
| `notApplicable` | la operación no aplica; no equivale a cero |

## 7. Contrato del trace

```json
{
  "traceSchemaVersion": "1.0.0",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "policyHash": "<sha256>",
  "engineVersion": "0.1.0",
  "subjectId": "stu_01J...",
  "resultStageId": "final-grade",
  "stages": [
    {
      "stageId": "presentation-score",
      "phase": "aggregation",
      "operator": "weightedAverage",
      "operatorVersion": "1.0.0",
      "applied": true,
      "inputRefs": ["EV1", "EV2", "EV3", "EV4"],
      "normalizedInputs": [{"ref": "EV1", "value": "78.4000", "unit": "percent"}],
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

- Los valores decimales se serializan con `decimal_str` (canónico, sin exponente).
- Una regla no aplicada aparece con `applied: false` y `decisions: ["not applied: ..."]`.
- Prohibido en el trace: RUT, nombre, email, paths privados, evidence content, secretos.

## 8. Outcome calculado

```json
{
  "schemaVersion": "1.0.0",
  "outcomeId": "out_01a2...",
  "subjectId": "stu_01J...",
  "resultStageId": "final-grade",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "value": "5.38",
  "unit": "grade",
  "status": "finalized",
  "finalizable": true,
  "traceHash": "<sha256 del trace>"
}
```

- `outcomeId` determinista: `out_` + primeros 16 bytes de
  `sha256(sectionId|subjectId|resultStageId|policyId)`.
- `status`: `finalized` | `pending` (missingPolicy `pending`).
- No se usa un assessmentId falso para la nota final.

## 9. Schema versioning

- `policy.schema.json` (C2): `schemaVersion` const `1.0.0`.
- `outcomes.schema.json`: `schemaVersion` const `1.0.0`.
- `traces.schema.json`: `traceSchemaVersion` const `1.0.0`.
- El verificador de snapshot selecciona schema por `schemaVersion` + `mode`.
- Major desconocida → `SchemaError` (fail-closed). Minor compatible: aditivo.

## 10. Snapshot C2 (`build --grade-policy`)

`canonical/policy.json` (mode `grade-policy-effective`):

```json
{
  "schemaVersion": "1.0.0",
  "policySchemaVersion": "1.0.0",
  "mode": "grade-policy-effective",
  "calculationAuthority": "grade-policy-engine",
  "policyId": "policy_fpy_2026_v1",
  "policyVersion": "1.0.0",
  "engineVersion": "0.1.0",
  "policyHash": "<sha256>",
  "policy": { "schemaVersion": "1.0.0", "...": "documento completo de policy" }
}
```

- `policyHash` = sha256 de la serialización canónica del documento `policy`.
- `canonical/outcomes.json` y `canonical/traces.json` se añaden a `manifest.files`,
  `contentHash` y `reviewHash`.
- Un fallo de policy no deja staging parcial.

## 11. Ejemplos inválidos (rechazados por validación)

- Operador desconocido: `{"operator": "magicAverage"}`.
- Condición textual libre: `"when": "level>=4"`.
- Ciclo: `a -> b -> a`.
- Self-reference: `{"ref": "a"}` dentro del stage `a`.
- Unidad incompatible: `additiveBonus` de `points` sobre `percent` sin conversión.
- Pesos que no suman 1: `0.1 + 0.1 + 0.1`.
- `cap` con unidad distinta a la del target.
- `excludeAndRenormalize` en `sum`.
- `round` en fase `aggregation`.
- `resultStageId` inexistente o inalcanzable.
- `assessmentId` duplicado o referencia inexistente.
- Campos desconocidos (schema `additionalProperties: false`).
- `engineMinVersion` mayor que la versión del engine instalado.

## 12. Exit codes CLI

- `0` éxito.
- `1` error de uso / estado inválido.
- `2` fallo de gate (schema, semántica, privacidad) — fail-closed.
