# C2 — Reporte de verificación

Corte **C2 — Grade Policy Engine** (motor determinista de políticas de
calificación), branch `feat/c2-grade-policy-engine`. Engine Decimal tipado con
catálogo cerrado V1 de operadores y condiciones, validación de policy por
schema (Draft 2020-12) + semántica, traces estructurados, integración aditiva
con los snapshots de publicación C1 (`--grade-policy`) y CLI operacional.

## Base

- `master` en el estado de C1 (C1 119 tests + E2E OK, C0 92 tests OK, scan
  estricto `BLOCK=0 REVIEW=0`).
- Al inicio de C2: árbol limpio, C1 y C0 verdes, `HEAD` `2cf34a93` (merge C0)
  + commits C1 posteriores.

## Resultado

| Check | Resultado |
|---|---|
| C2 suite unittest (57 tests: schema gates, semantic gates, 8 operadores, 4 condiciones, determinismo Decimal, exactitud 0.1+0.2, aislamiento de contexto, integración de snapshot, inyección de fallos) | `OK` |
| C2 self-check E2E sintético (`calculate` weightedAverage + round → `SUBJ-E2E → 76`) | `OK` |
| Regresión C1 (119 tests + E2E synthetic) | `OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto | `BLOCK=0 REVIEW=0` |
| Reproducibilidad del snapshot C2 | contentHash idéntico en builds repetidos (mismo epoch) |
| Dependencia | `jsonschema==4.10.3` pinneada en `engine/grade_policy/requirements.txt` |
| CI remoto | `.github/workflows/c2.yml` (suite C2, regresión C1, regresión C0, scan estricto) |

## Alcance implementado

- `engine/grade_policy/` (package 0.1.0): `decimal` (autoridad `Decimal`, contexto
  fijo `prec=28 ROUND_HALF_EVEN`, `WEIGHT_SUM_TOLERANCE=1e-9`, serialización
  canónica), `models` (`AcademicValue`, `AssessmentInput`, `NormalizedInputs`,
  `EvalContext`, `EngineOutcome`, `StageSpec`), `conditions` (4 condiciones + params
  schema), `graph` (plan topológico, rechazo de ciclos/stages muertos/inalcanzables),
  `validator` (gates schema + semántica con findings), `registry` (catálogo cerrado),
  `version`, `serialize` (canónico autónomo), `trace` (outcomes/traces), `snapshot`
  (`build_c2_payloads`), `engine` (`calculate` puro), `errors` tipados.
- `engine/grade_policy/operators/`: `base` + 8 operadores V1 (`weightedAverage`,
  `sum`, `piecewiseLinearScale`, `additiveBonus`, `replaceLowestInput`, `cap`,
  `floor`, `round`), unidades y fases restringidas por registro.
- `engine/grade_policy/schemas/`: `policy.schema.json`, `outcomes.schema.json`,
  `traces.schema.json` versionados + selector por `schemaVersion` (fail-closed).
- Integración publicación (aditiva): `builder.BuildContext.grade_policy_source` +
  hook `build_c2_payloads`; `hashing.EXPECTED_FILE_META` con
  `canonical/outcomes.json` y `canonical/traces.json`; `verify` mode-aware (G5 C2:
  `policyId/policyVersion/engineVersion/policyHash` + policy completa, cross-refs
  outcomes/traces, huérfanos/duplicados/mismatch); schema `policy-grade-policy` nuevo
  (C1 `policy.schema.json` intacto); `publication_snapshot.py --grade-policy`.
- CLI `engine/scripts/grade_policy.py` + wrapper `scripts/grade-policy.sh`
  (validate/calculate/explain/registry/test) + runner `grade_policy_test.py`.
  Exit codes 0/1/2.
- Tests: `engine/grade_policy/tests/` (`test_conformance.py`, `test_property.py`,
  `test_snapshot_integration.py`) + runner. Allowlist de fixtures sintéticos C2.
- CI `.github/workflows/c2.yml`.
- Docs: plan, contrato, runbooks (este reporte).

## Gates

- Schema (Draft 2020-12): política 1.0.0, outcomes 1.0.0, traces 1.0.0
  (`traceSchemaVersion`); major desconocida falla cerrado.
- Semántico: pesos suman 1, refs existen, etapas alcanzables desde
  `resultStageId`, sin ciclos, fases de operador y unidades compatibles,
  `missingPolicy` permitido por operador.
- `policyHash`: sha256 de los bytes canónicos de la policy.
- `outcomeId`: `out_` + sha256 truncado de `sectionId|subjectId|resultStageId|policyId`.
- Snapshots C2: manifest files/contentHash/reviewHash cubren los tres archivos C2;
  un build fallido no deja staging parcial; los snapshots legacy son byte-compatibles.

## Conformidad con el contrato

- §7 trace: `traceSchemaVersion 1.0.0`, decisiones de missing y warnings por stage.
- §9 versionado: schemas versionados + selección por versión/mode, sin fallback.
- §10 snapshot C2: `canonical/policy.json` (`grade-policy-effective`),
  `canonical/outcomes.json`, `canonical/traces.json` bajo manifest/contentHash/reviewHash.
- §4–§6 operadores/condiciones V1 cerrados, unidades/fases por registro y missing
  policies; §12 exit codes CLI 0/1/2.
- §13 FPY1101: solo reglas verificadas (`weighted_average`, `percent_to_grade`,
  defaults de `engine/defaults.json`); PCT/EvG modelados como
  `additiveBonus`+cap y `replaceLowestInput`+`levelAtLeast`.
- §15 compatibilidad: camino legacy sin `--grade-policy` byte-compatible;
  schemas C1 intactos; verifier aditivo por `mode`.

## Commits

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

## Observaciones

- El scanner requiere allowlist para los RUT sintéticos de los fixtures C2
  (`engine/c0/allowlist.json`, entrada `engine/grade_policy/tests/**`).
- La autoridad numérica es siempre `Decimal`; no existe float binario en el camino
  de cálculo; el contexto decimal ambiental no afecta los resultados (aislado).
- Un snapshot C2 fallido (policy inválida, assessment ausente, `missingPolicy:
  fail` sin score) se detiene antes de escribir staging; no hay publicación parcial.
- Los snapshots legacy-effective no cambian: misma verificación y compatibilidad C1.
