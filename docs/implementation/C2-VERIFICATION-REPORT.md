# C2 — Reporte de verificación

Corte **C2 — Grade Policy Engine** (motor determinista de políticas de
calificación), branch `feat/c2-grade-policy-engine`. Este reporte cubre la
quinta iteración de C2: cierre de la frontera de autoridad entre
`canonical/results.json` y el Grade Policy Engine (unidades explícitas en
snapshot, selección de attempts, score inválido, fixtures reales). Motor
`0.2.0`; `outcomes`/`traces` en schema `1.1.0` (aditivo; 1.0.0 conservado y
aún válido).

## Base

- `master` en el estado de C1 (C1 119 tests + E2E OK, C0 92 tests OK, scan
  estricto `BLOCK=0 REVIEW=0`).
- Rama `feat/c2-grade-policy-engine` sobre `master`; PR #5 (Draft, open).
- Head verificado: `61dde30` (código y tests de la iteración 5; frontera de
  autoridad cerrada entre canonical/results.json y el engine).

## Resultado

| Check | Resultado |
|---|---|
| C2 suite unittest (**199 tests**: schema/semantic gates, DAG + aristas de condición y de refs de operador, paridad con el ejemplo oficial §2 **copiado literalmente** del contrato, restricción V1 del target de `replaceLowestInput`, `zero` de `piecewiseLinearScale`, propagación de unidades, matriz de missing policies, estados tipados, trazas 1.1.0 con `operatorData`, determinismo Decimal, integración de snapshot, inyección de fallos, introspección de specs de operadores, sin errores crudos en runtime, **frontera de autoridad canonical** — unidades explícitas sin `or "percent"`, rechazo de attempts duplicados, score inválido tipado, precondición C1) | `OK` |
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
  `graph`, `units` (`propagate_units` topológico, no adivina), `validator`,
  `registry`, `version`, `serialize`, `trace`, `snapshot`, `engine`, `errors`
  tipados.
- `engine/grade_policy/operators/`: 8 operadores V1 con params tipados según el
  contrato. En esta iteración:
  - `replaceLowestInput`: target restringido en V1 (ver § Hallazgo 2);
  - `piecewiseLinearScale`: `zero` con unidad del input ref, check de rango
    antes de escalar (ver § Hallazgo 3).
- `engine/grade_policy/snapshot.py`: el adaptador de canonical es **fail-closed**:
  todo assessment que la policy usa debe declarar su unidad en
  `assessmentUnits` (nunca cae silenciosamente a `percent`); más de un
  resultado para el mismo `(studentId, assessmentId)` es rechazado
  (`DuplicateAttemptError`); score no finito o no parseable es rechazado
  (`InvalidScoreError`); la estructura C1 se valida antes de calcular
  (`CanonicalFormatError`). El modo standalone (CLI con inputs tipados) puede
  resolver unidades desde los inputs; el modo snapshot no.
- `engine/grade_policy/errors.py`: tres nuevos errores tipados
  (`CanonicalFormatError`, `DuplicateAttemptError`, `InvalidScoreError`).
- Tests (10 archivos): `test_conformance.py`, `test_property.py`,
  `test_dag_conditions.py`, `test_units.py`, `test_missing_policies.py`,
  `test_states.py`, `test_snapshot_integration.py`, `test_contract_parity.py`,
  `test_no_unhandled_exceptions.py`, `test_operator_specs.py`,
  `test_canonical_boundary.py` (unidades explícitas, selección de attempts,
  score inválido, precondición C1).
- Docs: plan, contrato, runbooks y este reporte.

## Hallazgos residuales cerrados

### 0. Frontera de autoridad canonical/results.json ↔ engine (iteración 5)

El modo snapshot es la frontera de autoridad entre `canonical/results.json` y
el engine de policy, y es **fail-closed** (los payloads canonical de C1 no
llevan unidad, por lo que el engine nunca adivina):

- **Unidades explícitas**: se eliminó `or "percent"` en `build_c2_payloads`;
  todo assessment que la policy usa debe declarar su unidad en
  `assessmentUnits`. Un assessment sin unidad declarada es rechazado
  (`SemanticValidationError`) — nunca cae silenciosamente a `percent`. El modo
  standalone (CLI con inputs tipados) sí puede resolver unidades desde los
  inputs; el modo snapshot no.
- **Selección de attempts fuera de C2 V1**: más de un resultado para el mismo
  `(studentId, assessmentId)` es rechazado con `DuplicateAttemptError` (tipado
  y sanitizado). El orden del array nunca es política de selección; no existe
  "último", "primero" ni "mejor" implícito. Seleccionar entre intentos
  múltiples requerirá una policy explícita futura.
- **Score inválido**: se reemplazó el catch-all `except Exception: return None`
  en `_to_score`. `null`/vacío es `missing` (gestionado por la missing policy
  del stage); un número válido se convierte con `to_decimal`; un valor no vacío
  que no parsea, o `NaN`/`Infinity`, es un error tipado (`InvalidScoreError`) —
  los errores de datos **nunca** se convierten en missing policy. El mensaje no
  incluye el valor crudo ni PII (no name/RUT/email/path).
- **Precondición estructural C1**: `build_c2_payloads` valida la estructura C1
  de `subjects.json`, `assessments.json` y `results.json` (`schemaVersion`,
  `sectionId`, `studentId` opaco `stu_…`, `attemptId` opaco `att_…`, `status`,
  `components`, `score`). Una estructura incompleta es `CanonicalFormatError` —
  el snapshot no se calcula sobre estructuras incompletas.
- **Fixtures reales**: los tests de snapshot del ejemplo oficial usan payloads
  canonical válidos según los schemas C1 (opaque ids, attemptId, status,
  components, score). `test_canonical_boundary.py` cubre los cuatro ejes con
  datos sintéticos completos.

### 1. Contrato oficial (C2-GRADE-POLICY-CONTRACT.md)

- `condition` se movió desde `replaceLowestInput.params` a `stage.condition`.
- La fuente del reemplazo es `PCT` (`percent`); `EvG` (`level`) se usa solo como
  condición `levelAtLeast`.
- `scoreAtLeast`/`scoreBelow` usan `threshold: {value, unit}`.
- Se eliminaron las policies de ejemplo que el engine rechazaba.
- El ejemplo §2 ahora **valida sin modificación**, calcula un outcome final
  (`5.56` grade) y genera snapshot C2. El test de paridad lo **copia
  literalmente** desde el documento (extrae el bloque JSON de la sección §2 y lo
  carga sin transformación).

### 2. Restricción V1 del target de `replaceLowestInput`

Para cerrar C2 sin ampliar el contexto de ejecución:

- `target` debe ser `weightedAverage`; `target.missingPolicy` debe ser `fail` o
  estar ausente; `target` no puede tener `condition`.
- Al ejecutar, `target` debe estar en `state=value`; el runtime resuelve el
  estado del target **antes** de leer candidatos.
- Todos los candidatos del target están presentes; sus pesos son positivos y
  suman 1; los pesos originales **son** los pesos efectivos (sin exclusión ni
  renormalización).
- El validator rechaza target con `zero`, `excludeAndRenormalize`,
  `minimumOutput`, `pending`, `notApplicable` o `condition`.
- Tests: target válido, target `pending` rechazado por validation y propagado en
  runtime como error tipado, target `skippedCondition` rechazado, target
  `excludeAndRenormalize`/`zero` rechazados, pesos utilizados iguales a los del
  target.
- Limitación documentada explícitamente en el contrato §6 y en los runbooks.

### 3. `zero` en `piecewiseLinearScale`

En `missingPolicy=zero`:

- La unidad esperada se obtiene del **input ref** (nunca de `params.outputUnit`).
- El cero se crea en la unidad de entrada; `_check_outside` se ejecuta **antes**
  de `_scale`.
- `outsideRange=reject` lanza `OutOfRangeError`; `clamp` produce el extremo
  correspondiente.
- Tests: input `percent` → output `grade`, cero dentro del rango, cero fuera del
  rango con `clamp`, cero fuera del rango con `reject`, trace conserva la
  decisión `zero`, paridad de unidad estática/runtime del output.

## Gates

- Schema (Draft 2020-12): policy `1.0.0`; outcomes/traces `1.1.0` (y `1.0.0`
  conservado); major desconocida falla cerrado.
- Semántico: pesos suman 1 (solo `weightedAverage`), refs existen,
  `resultStageId` alcanzable, sin ciclos (incluyendo aristas de condición y de
  refs de operador), sin dependencias hacia fases posteriores, aridad por
  operador, params tipados por operador, target de `replaceLowestInput`
  restringido en V1, unidad tipada (estática == runtime, fail-closed),
  `minimumOutput` exige `params.minimum {value, unit}`, missing policy dentro de
  la matriz exacta, condición con `params.ref` y ref-kind por condición,
  threshold tipado, `levelAtLeast` exige unidad `level` y `level` ∈ catálogo.
- Runtime: unidades mezcladas rechazadas; `zero` con la unidad esperada del
  input; sin inputs presentes con unidad no declarada → error tipado; target de
  `replaceLowestInput` fuera de `state=value` → error tipado antes de leer
  candidatos.
- `policyHash`: sha256 de los bytes canónicos de la policy.
- `outcomeId`: `out_` + sha256 truncado de `sectionId|subjectId|resultStageId|policyId`.
- Snapshots C2: manifest files/contentHash/reviewHash cubren los artefactos C2;
  un build fallido no deja staging parcial; los snapshots legacy son
  byte-compatibles.
- Frontera de autoridad (snapshot mode): unidades explícitas requeridas
  (`SemanticValidationError` si falta); attempts duplicados rechazados
  (`DuplicateAttemptError`); score inválido rechazado (`InvalidScoreError`);
  estructura C1 validada (`CanonicalFormatError`).

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

Propagación hacia abajo con motivo; `finalizable` solo cuando el stage de
resultado está en `value`.

## Conformidad con el contrato

- §2 documento: ejemplo oficial válido, copiado literalmente por el test;
  condiciones `{"kind", "params"}` en `stage.condition`.
- §4 estados tipados; §5 unidades (`zero` por unidad esperada del input;
  `piecewiseLinearScale` como único conversor); §6 matriz operador × policy ×
  unidades y restricción V1 del target; §7 condiciones con `params.ref` y
  threshold tipado `{value, unit}`; §8 missing policies; §9 trace 1.1.0; §10
  outcome 1.1.0; §11 schema versioning; §12 snapshot C2; §14 exit codes CLI 0/1/2.
- FPY1101: solo reglas verificadas (`weighted_average`, `percent_to_grade`,
  defaults de `engine/defaults.json`); PCT/EvG modelados como
  `additiveBonus`+cap y `replaceLowestInput`+`levelAtLeast`.
- Compatibilidad: camino legacy sin `--grade-policy` byte-compatible; schemas
  C1 intactos; verifier aditivo por `mode`/versión.

## Commits

Iteración 1 (base):

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

Iteración 3 (cierre de la divergencia contrato ↔ implementación): `1ad0e5e`,
`f26ba5c`, `b49fbdc`.

Iteración 4 (cierre de tres hallazgos residuales): `6c4b531`, `4f6f9ca`.

Iteración 5 (este reporte): cierre de la frontera de autoridad
canonical/results.json ↔ engine. Commit:

- `61dde30` feat: close authority frontier between canonical/results.json and
  grade policy engine

## CI

- Workflow `.github/workflows/c2.yml`: suite C2, regresión C1, regresión C0 y
  scan estricto.
- Estado remoto en el head verificado `61dde30`: **verde** — `C2 grade policy
  engine gates` success, `C1 publication snapshot gates` success, `C0 security
  gates` success.

## Observaciones y riesgos residuales

- La inferencia estática de unidades cubre solo `assessmentUnits` declaradas;
  las unidades no declaradas se resuelven en runtime (por diseño: no se adivina).
  Una policy sin `assessmentUnits` que combine unidades heterogéneas falla en
  runtime, no en validación. **En modo snapshot**, la falta de unidad es
  rechazada antes del cálculo (`SemanticValidationError`).
- `level` participa en condiciones `levelAtLeast`; no hay operaciones
  aritméticas sobre unidades `level`.
- La restricción V1 del target de `replaceLowestInput` es una limitación
  deliberada de V1: un target con exclusión/renormalización o condición
  requeriría ampliar el contexto de ejecución del operador y queda fuera de C2.
- La matriz exacta se impone en validación semántica (no expresable en JSON
  Schema); quedó cubierta por `test_missing_policies.py` y
  `test_contract_parity.py`.
- **Selección de attempts múltiples queda fuera de C2 V1**: un future policy
  explícita sería necesaria para elegir entre múltiples intentos
  (first/last/best son todos rechazados como reglas implícitas).
