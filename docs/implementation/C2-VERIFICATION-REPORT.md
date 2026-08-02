# C2 — Reporte de verificación

Corte **C2 — Grade Policy Engine** (motor determinista de políticas de
calificación), branch `feat/c2-grade-policy-engine`. Este reporte cubre la
segunda iteración de C2: corrección de inconsistencias semánticas (aristas de
condición en el DAG, propagación tipada de unidades, matriz exacta de missing
policies y estados tipados por stage). Motor `0.2.0`; `outcomes`/`traces` en
schema `1.1.0` (aditivo; 1.0.0 conservado y aún válido).

## Base

- `master` en el estado de C1 (C1 119 tests + E2E OK, C0 92 tests OK, scan
  estricto `BLOCK=0 REVIEW=0`).
- Rama `feat/c2-grade-policy-engine` sobre `master`; PR #5 (open, mergeable).
- Head verificado: `1ad0e5e` (contiene este reporte).

## Resultado

| Check | Resultado |
|---|---|
| C2 suite unittest (107 tests: schema/semantic gates, DAG + aristas de condición, propagación de unidades, matriz de missing policies, estados tipados, trazas 1.1.0, determinismo Decimal, integración de snapshot, inyección de fallos) | `OK` |
| C2 self-check E2E sintético (`calculate` weightedAverage + round → `SUBJ-E2E → 76`) | `OK` |
| Regresión C1 (119 tests + E2E synthetic) | `OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto (`c0-scan.sh --tracked --strict`) | `BLOCK=0 REVIEW=0` (227 archivos) |
| `git diff --check master...HEAD` | limpio |
| Dependencia | `jsonschema==4.10.3` pinneada en `engine/grade_policy/requirements.txt` |
| CI remoto | `.github/workflows/c2.yml` (suite C2, regresión C1, regresión C0, scan estricto) — ver § CI |

## Alcance implementado

- `engine/grade_policy/` (package `0.2.0`): `decimal`, `models` (estados tipados
  `StageState`, `MissingDecision`, `ResolvedInput`, `EvalContext` con
  `stage_states`/`stage_reasons`/`units`/`resolve_ref`, `EngineOutcome` con
  `state`/`finalizable`/`stages`), `conditions` (6 condiciones, `params.ref`),
  `graph` (`condition_refs` lee `condition.params.ref`; aristas de condición de
  primera clase; `topological_order` separado de `plan`; detección de
  ciclos/stages muertos/inalcanzables), `units` (`propagate_units` topológico,
  no adivina), `validator` (gates de unidad tipados, orden de fases,
  `minimumOutput`/`outputUnit`, mezcla de unidades estática), `registry`,
  `version`, `serialize`, `trace` (1.1.0: `resultState`, `finalizable`,
  `missingDecisions`, estados por input), `snapshot`, `engine` (ejecución pura
  con propagación de estados y motivos), `errors` tipados.
- `engine/grade_policy/operators/`: `base` (`OperatorSpec.resolve_output_unit`,
  helpers de missing policies) + 8 operadores V1 reescritos con su matriz exacta
  de missing policies.
- `engine/grade_policy/schemas/`: `policy.schema.json` (con `assessmentUnits`),
  `outcomes-1.1.0.schema.json` y `traces-1.1.0.schema.json` (nuevos) +
  versiones 1.0.0 intactas; selector por `schemaVersion` (fail-closed).
- Integración publicación (aditiva): hook `build_c2_payloads`; verifier
  mode-aware que valida los artefactos C2 contra el schema `1.1.0` declarado.
- CLI `engine/scripts/grade_policy.py` (0.2.0) + wrapper
  `scripts/grade-policy.sh`; `explain` imprime estados tipados y
  `missingDecisions`; `calculate` emite `1.1.0` con `resultState`/`finalizable`.
- Tests (7 archivos): `test_conformance.py`, `test_property.py`
  (incluye propagación de unidades), `test_dag_conditions.py`,
  `test_units.py`, `test_missing_policies.py`, `test_states.py`,
  `test_snapshot_integration.py`.
- Docs: plan, contrato, runbooks y este reporte.

## Gates

- Schema (Draft 2020-12): policy `1.0.0`; outcomes/traces `1.1.0` (y `1.0.0`
  conservado); major desconocida falla cerrado.
- Semántico:
  - pesos suman 1, refs existen, `resultStageId` alcanzable, sin ciclos
    (incluyendo aristas de condición), sin dependencias hacia fases posteriores;
  - unidad tipada: `assessmentUnits` declaradas, unidad estática == unidad de
    runtime (`UnitMismatchError` en caso contrario), sin adivinanzas;
  - `piecewiseLinearScale` exige `params.outputUnit`; `minimumOutput` exige
    `params.minimum {value, unit}`;
  - `missingPolicy` dentro de la matriz exacta del operador;
  - condición con `params.ref` inexistente → fallo cerrado.
- Runtime: unidades mezcladas conocidas rechazadas; `zero` rellena con la
  unidad esperada del stage (nunca una unidad global); sin inputs presentes con
  unidad no declarada → error tipado.
- `policyHash`: sha256 de los bytes canónicos de la policy.
- `outcomeId`: `out_` + sha256 truncado de `sectionId|subjectId|resultStageId|policyId`.
- Snapshots C2: manifest files/contentHash/reviewHash cubren los artefactos C2;
  un build fallido no deja staging parcial; los snapshots legacy son
  byte-compatibles.

## Matriz exacta missing policies (probada)

| Operador | `fail` | `zero` | `excludeAndRenormalize` | `minimumOutput` | `pending` | `notApplicable` |
|---|---|---|---|---|---|---|
| `weightedAverage` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `sum` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `cap` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `floor` | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| `round` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ |
| `additiveBonus` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ |
| `replaceLowestInput` | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ |
| `piecewiseLinearScale` | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |

## Estados tipados de stage

| Estado | Resultado |
|---|---|
| `value` | `finalized` |
| `pending` (sin inputs presentes) | `pending` |
| `notApplicable` | `notApplicable` |
| `skippedCondition` (condición no satisfecha) | `pending`, no finalizable |

Propagación hacia abajo con motivo (p. ej. `pending` por `missing` upstream);
`finalizable` solo cuando el stage de resultado está en `value`.

## Conformidad con el contrato

- §2 documento: `assessments` + `assessmentUnits` + `stages` keyed por id;
  condiciones `{"kind", "params"}`.
- §4 estados tipados; §5 unidades (inferencia estática sin adivinanzas, `zero`
  por unidad esperada, `outputUnit` explícito); §6 matriz operador × policy ×
  unidades; §7 condiciones con `params.ref` como arista del DAG; §8 missing
  policies; §9 trace 1.1.0; §10 outcome 1.1.0 con `resultState`/`finalizable`;
  §11 schema versioning; §12 snapshot C2; §14 exit codes CLI 0/1/2.
- FPY1101: solo reglas verificadas (`weighted_average`, `percent_to_grade`,
  defaults de `engine/defaults.json`); PCT/EvG modelados como
  `additiveBonus`+cap y `replaceLowestInput`+`levelAtLeast`.
- Compatibilidad: camino legacy sin `--grade-policy` byte-compatible; schemas
  C1 intactos; verifier aditivo por `mode`/versión.

## Commits

Iteración 1 (base, pre-fix):

- `04ed05d` docs: define C2 grade policy implementation plan
- `43f75e4` docs: define C2 grade policy contracts
- `d3e7f38` feat: add versioned grade policy schemas
- `80f8ba8` feat: add closed operator and condition registries
- `9fc812a` feat: add semantic policy validator and DAG planner
- `c8ed226` feat: add deterministic decimal grade engine
- `84872ef` feat: add structured calculation traces
- `3457a9a` feat: integrate grade policy with publication snapshots
- `6a27ee6` feat: add grade policy CLI
- `c974a97` test: add C2 conformance and property suites
- `baddb6f` test: add C2 snapshot integration and failure-injection suite
- `2db987f` ci: add C2 grade policy engine gates
- `796b6eb` docs: add C2 runbooks and verification report

Iteración 2 (este reporte): fixes de consistencia semántica (DAG/condiciones,
unidades tipadas, missing policies, estados), engine `0.2.0`, schemas `1.1.0`,
4 suites nuevas y docs actualizadas.

- `1ad0e5e` feat: harden C2 engine semantics (typed units, states, missing policies)

## CI

- Workflow `.github/workflows/c2.yml`: suite C2, regresión C1, regresión C0 y
  scan estricto.
- Estado remoto en el head verificado `1ad0e5e`: **verde** — `C2 grade policy
  engine gates` success, `C1 publication snapshot gates` success, `C0 security
  gates` success.

## Observaciones y riesgos residuales

- La inferencia estática de unidades cubre solo `assessmentUnits` declaradas;
  las unidades no declaradas se resuelven en runtime (por diseño: no se adivina).
  Una policy sin `assessmentUnits` que combine unidades heterogéneas falla en
  runtime, no en validación.
- `level` participa en condiciones `levelAtLeast`; no hay operaciones
  aritméticas sobre unidades `level`.
- La matriz exacta se impone en validación semántica (no expresable en JSON
  Schema); quedó cubierta por `test_missing_policies.py`.
