# C2 — Runbooks operativos

Operaciones del motor de políticas de calificación (grade policy engine) para el
corte C2. Dos frentes:

1. CLI de policy: `./scripts/grade-policy.sh` (validate/calculate/explain/registry/test).
2. Integración con snapshot de publicación: `./scripts/publication-snapshot.sh build --grade-policy <file>`.

## Exit codes

- `0` éxito.
- `1` error de uso / estado inválido (por ejemplo, archivo de inputs malformado).
- `2` fallo de gate (schema, semántica, policy no representable) — fail-closed.

## CLI de policy

```bash
# Validar una policy (gate de schema + gate semántico, fail-closed)
./scripts/grade-policy.sh validate <policy.json>

# Ejecutar el engine sobre un archivo de inputs (outcomes JSON en stdout)
./scripts/grade-policy.sh calculate <policy.json> --inputs <inputs.json> [--section <SECTION_CODE>]

# Traza humana por etapa
./scripts/grade-policy.sh explain <policy.json> --inputs <inputs.json> [--section <SECTION_CODE>]

# Catálogo cerrado V1 (operadores, condiciones, unidades, fases)
./scripts/grade-policy.sh registry

# Suite C2 (conformance + property + integración + E2E)
./scripts/grade-policy.sh test
```

### Formato de inputs

`inputs.json` es un objeto con `subjects`, un mapping de `subjectId` opaco →
`assessmentId` → `{present, value, unit, status}`:

```json
{
  "subjects": {
    "stu_abcdef0123456789": {
      "presentacion": {"present": true,  "value": "70", "unit": "percent", "status": "Evaluada"},
      "examen":        {"present": false}
    }
  }
}
```

Los valores son cadenas decimales (nunca float binario); la autoridad numérica es
`Decimal`. Un assessment ausente se declara con `present: false`.

### Ejemplo de policy

```json
{
  "schemaVersion": "1.0.0",
  "policyId": "seccion-fp2111-p1",
  "policyVersion": "1.0.0",
  "engineMinVersion": "0.1.0",
  "assessments": ["presentacion", "examen"],
  "stages": {
    "w": {
      "id": "w",
      "phase": "aggregation",
      "operator": "weightedAverage",
      "inputs": [
        {"ref": "presentacion", "weight": "0.6"},
        {"ref": "examen", "weight": "0.4"}
      ],
      "missingPolicy": "zero"
    },
    "final": {
      "id": "final",
      "phase": "finalization",
      "operator": "round",
      "inputs": [{"ref": "w"}],
      "params": {"decimalPlaces": 2, "mode": "halfUp"}
    }
  },
  "resultStageId": "final"
}
```

## Snapshot con policy C2

```bash
export SECTION_CODE=FP2111-S1
./scripts/export-results.sh                      # regenera exports/publication-input/

# build C2: canonical + policy efectiva + outcomes + traces en el manifest
./scripts/publication-snapshot.sh --section "$SECTION_CODE" build --grade-policy <policy.json>
```

El snapshot resultante declara `canonical/policy.json` en mode
`grade-policy-effective` (con la policy completa, `policyId`, `policyVersion`,
`engineVersion` y `policyHash`), y los tres archivos C2 quedan cubiertos por
`manifest.files`, `contentHash` y `reviewHash`. Verificación, review y approve
siguen el flujo C1 sin cambios:

```bash
RH=<reviewHash-impreso-por-build>
./scripts/publication-snapshot.sh --section "$SECTION_CODE" verify --target staging
./scripts/publication-snapshot.sh --section "$SECTION_CODE" review --review-hash "$RH" --reviewer reviewer-a
./scripts/publication-snapshot.sh --section "$SECTION_CODE" approve --review-hash "$RH" --approver approver-a --confirm approve
```

Un snapshot legacy (sin `--grade-policy`) es byte-compatible con C1 y sigue
verificándose sin cambios.

## Verificación

```bash
./scripts/grade-policy.sh test                                                    # suite C2 completa
./scripts/publication-snapshot.sh --section "$SECTION_CODE" verify --target staging
```

## Fallos y recuperación

| Fallo | Señal | Recuperación |
|---|---|---|
| Policy no es JSON / no es objeto | exit `1` (`SchemaValidationError`) | corregir policy |
| Schema de policy inválido | exit `2` con findings | corregir policy |
| Operador/condición desconocido | exit `2`, fallo cerrado | corregir policy |
| Ciclo o stage muerto en el DAG | exit `2`, `CycleError` | corregir policy |
| Unidad incompatible entre etapas | exit `2` | corregir policy |
| Pesos no suman 1 | exit `2`, `WeightSumError` | corregir policy |
| Assessment faltante (missingPolicy `fail`) | exit `2`, `MissingInputError` | inputs o missingPolicy |
| Assessment de policy ausente del canonical | build falla sin staging parcial | corregir policy o export |
| Archivo de policy inexistente | exit `1` `UsageError`, sin staging | crear el archivo |
| Outcome/trace tampered tras review | `verify` falla | crear corrección |
| Policy/engine version cambiadas tras review | approval rechazado | nuevo review |

Un build C2 fallido nunca deja un snapshot parcial bajo
`ACADGRAD_PUBLICATIONS_ROOT`; los residuos de staging se descartan con
`discard` (igual que C1).

## Self-check

```bash
./scripts/grade-policy.sh test
```

Ejecuta la suite unittest de C2 (conformance, property, integración de snapshot,
inyección de fallos) y un escenario E2E sintético de `calculate`.
