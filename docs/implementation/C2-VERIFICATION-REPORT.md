# C2 — Reporte de verificación

Corte **C2 — Grade Policy Engine** (motor determinista de políticas de
calificación), branch `feat/c2-grade-policy-engine`. Este reporte cubre la
tercera iteración de C2: cierre de la divergencia entre el contrato y la
implementación (params tipados de operadores, condiciones unit-aware, aristas de
refs de operador en el DAG, paridad contra los ejemplos oficiales del contrato,
sin errores crudos en runtime). Motor `0.2.0`; `outcomes`/`traces` en schema
`1.1.0` (aditivo; 1.0.0 conservado y aún válido).

## Base

- `master` en el estado de C1 (C1 119 tests + E2E OK, C0 92 tests OK, scan
  estricto `BLOCK=0 REVIEW=0`).
- Rama `feat/c2-grade-policy-engine` sobre `master`; PR #5 (open, mergeable).
- Head verificado: `f26ba5c` (contiene este reporte).

## Resultado

| Check | Resultado |
|---|---|
| C2 suite unittest (159 tests: schema/semantic gates, DAG + aristas de condición y de refs de operador, paridad con los ejemplos oficiales del contrato, propagación de unidades, matriz de missing policies, estados tipados, trazas 1.1.0 con `operatorData`, determinismo Decimal, integración de snapshot, inyección de fallos, introspección de specs de operadores, sin errores crudos en runtime) | `OK` |
| C2 self-check E2E sintético (`calculate` weightedAverage + round → `SUBJ-E2E → 76`) | `OK` |
| Regresión C1 (119 tests + E2E synthetic) | `OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto (`c0-scan.sh --tracked --strict`) | `BLOCK=0 REVIEW=0` |
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
- `engine/grade_policy/operators/`: `base` (`OperatorSpec` ampliado con
  `OperatorReference`/`referenced_refs`/`min_inputs`/`max_inputs`/`weight_rule`/
  `semantic_validate`) + 8 operadores V1 con params tipados según el contrato:
  `cap`/`floor` con bounds `{value, unit}` obligatorios, `sum` con `cap`/`floor`
  opcionales tipados, `piecewiseLinearScale` con `breakpoints [{x,y}]` +
  `outputUnit` + `outsideRange` (clamp/reject, `OutOfRangeError`),
  `additiveBonus` con `target`/`source`/`cap`, `replaceLowestInput` con
  `target`/`source`/`tiePolicy` (recalcula el promedio ponderado del target,
  nunca una suma), `weightedAverage` sin `params.weights` (pesos solo en
  `InputRef`), `round` con `decimalPlaces` o `quantum`. `EvalResult`/traces
  registran `operatorData` por stage.
- `engine/grade_policy/conditions.py`: 6 condiciones unit-aware (`statusEquals`/
  `assessmentPresent`/`assessmentMissing` con ref=assessment; `scoreAtLeast`/
  `scoreBelow` con threshold `{value, unit}`; `levelAtLeast` con `level` y
  catálogo `levels` opcional); `CONDITION_REF_KINDS`.
- `engine/grade_policy/schemas/`: `policy.schema.json` (con `assessmentUnits`),
  `outcomes-1.1.0.schema.json` y `traces-1.1.0.schema.json` (nuevos, `operatorData`
  permitido) + versiones 1.0.0 intactas; selector por `schemaVersion` (fail-closed).
- Integración publicación (aditiva): hook `build_c2_payloads`; verifier
  mode-aware que valida los artefactos C2 contra el schema `1.1.0` declarado.
- CLI `engine/scripts/grade_policy.py` (0.2.0) + wrapper
  `scripts/grade-policy.sh`; `explain` imprime estados tipados y
  `missingDecisions`; `calculate` emite `1.1.0` con `resultState`/`finalizable`.
- Tests (9 archivos): `test_conformance.py`, `test_property.py`
  (incluye propagación de unidades), `test_dag_conditions.py`,
  `test_units.py`, `test_missing_policies.py`, `test_states.py`,
  `test_snapshot_integration.py`, `test_contract_parity.py`,
  `test_no_unhandled_exceptions.py`, `test_operator_specs.py`.
- Docs: plan, contrato, runbooks y este reporte.

## Gates

- Schema (Draft 2020-12): policy `1.0.0`; outcomes/traces `1.1.0` (y `1.0.0`
  conservado); major desconocida falla cerrado.
- Semántico:
  - pesos suman 1 (solo `weightedAverage`; pesos prohibidos en el resto), refs
    existen, `resultStageId` alcanzable, sin ciclos (incluyendo aristas de
    condición y de refs de operador), sin dependencias hacia fases posteriores,
    aridad por operador, refs de input duplicados;
  - params tipados por operador: `cap`/`floor`/`sum cap|floor` con `{value, unit}`,
    `piecewiseLinearScale` con `outputUnit` + `breakpoints` crecientes +
    `outsideRange`, `additiveBonus`/`replaceLowestInput` con refs existentes y
    unidades compatibles, `replaceLowestInput` con target `weightedAverage` y
    `tiePolicy` válido;
  - unidad tipada: `assessmentUnits` declaradas, unidad estática == unidad de
    runtime (`UnitMismatchError` en caso contrario), sin adivinanzas;
  - `minimumOutput` exige `params.minimum {value, unit}` con unidad del stage;
  - `missingPolicy` dentro de la matriz exacta del operador;
  - condición con `params.ref` inexistente → fallo cerrado; ref-kind por
    condición (`assessment` para `statusEquals`/`assessmentPresent`/
    `assessmentMissing`); threshold tipado; `levelAtLeast` exige unidad `level` y
    `level` ∈ catálogo `levels` cuando está presente.
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

## Paridad con el ejemplo oficial (§2)

El documento oficial del contrato se ejercita verbatim en
`test_contract_parity.py`. Dos tensiones internas del contrato se resuelven a
favor de disposiciones más claras:

- `condition` vive en `stage.condition`, no dentro de `params` (§2 Reglas del
  documento y §7 definen la condición como puerta de stage de primera clase;
  duplicarla en `params` rompería la única ubicación). Un `condition` dentro de
  `params` es rechazado.
- La fuente `EvG` del ejemplo es `level` mientras los candidatos del target son
  `percent`. §13 prohíbe mezclar unidades conocidas en un stage homogéneo y §6
  exige conservar la unidad del target; el motor rechaza esa mezcla en
  validación (mensaje `incompatible with candidate`) en lugar de fallar en
  runtime. La variante unit-coherente del pipeline se ejecuta end-to-end
  (evidencia esperada `5.56`).

Además, `levelAtLeast` acepta el catálogo `levels` (§7) y valida que `level`
pertenezca a él.

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

Iteración 3 (este reporte): cierre de la divergencia contrato ↔ implementación
(params tipados, condiciones unit-aware, refs de operador como aristas, paridad
con ejemplos oficiales, sin errores crudos en runtime), suites nuevas
(`test_contract_parity.py`, `test_no_unhandled_exceptions.py`,
`test_operator_specs.py`) y docs actualizadas. Commits a continuación de la
iteración 2 en el PR #5.

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
  Schema); quedó cubierta por `test_missing_policies.py` y
  `test_contract_parity.py`.
- El ejemplo oficial §2 mezcla `level`/`percent` en `replaceLowestInput`; se
  rechaza en validación (resolución documentada en § Paridad).
