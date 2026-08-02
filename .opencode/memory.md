# Memory: C2 Grade Policy Engine PR #5

## Objective
Todo: cerrar la divergencia entre `docs/implementation/C2-GRADE-POLICY-CONTRACT.md` y la implementación real de operadores, condiciones y validación en el PR #5 (rama `feat/c2-grade-policy-engine`, repo `cmartinezs/academic-grading-with-ai`). El contrato documentado es la autoridad; no se debilita el contrato excepto con contradicción arquitectónica demostrable.

## Important Details
- Restricciones: no crear otra rama, no abrir otro PR, no force-push, no marcar ready, no merge, no implementar C3–C7. Mantener PR Draft. Head esperado original: `f26ba5c...`; ahora el head real del PR es `b49fbdc` (commit de alineación con el contrato), estado OPEN + DRAFT, MERGEABLE, CI verde (c0/c1/c2 ×2).
- Baselines verificados antes de empezar: C2 = 107 tests OK, C0 = 92 OK, C1 = 119 OK + E2E OK.
- Contrato exige: `additiveBonus` params `target`/`source`/`cap` opcional tipado; `replaceLowestInput` params `target`/`source`/`tiePolicy` (target debe ser `weightedAverage`, recalcular promedio con pesos, no suma); `piecewiseLinearScale` params `breakpoints [{x,y}]`/`outputUnit`/`outsideRange` (clamp|reject), eliminar `pairs`/`from`/`to`; `cap`/`floor` con bounds tipados obligatorios; `sum` con `cap`/`floor` opcionales tipados; condiciones unit-aware (`levelAtLeast` lee AcademicValue con unit=level y compara value, no status; `scoreAtLeast`/`scoreBelow` con threshold `{value, unit}`; `statusEquals`/`assessmentPresent`/`assessmentMissing` ref=solo assessment).
- OperatorSpec debe declarar: `referenced_refs(stage) -> OperatorReference[]` (ref, role source|target|candidate, expected kind assessment|stage|either, required, expected unit), `min_inputs`/`max_inputs`, `weight_rule`, `semantic_validate`. stage.condition es la única ubicación de condiciones.
- Validación previa a calculate: aridad, dup refs, pesos positivos/suman 1±tol, `params.weights` eliminado (pesos solo en `InputRef`), bounds tipados, `minimumOutput.unit` compatible, breakpoints, tiePolicy, target operator kind, compatibilidad source/target. Ninguna policy validada debe producir IndexError/KeyError/TypeError/ZeroDivisionError en runtime.
- **Tensión interna del contrato descubierta**: el ejemplo oficial §2 usa `condition` dentro de `params` de replaceLowestInput y fuente `EvG` en unidad `level` sobre candidatos `percent`. Resolución: condiciones SIEMPRE en `stage.condition` (§2 reglas + §7); la mezcla level/percent se RECHAZA en validación (consistente con §6 "inputs homogéneos" + §13 "mezcla de unidades conocidas" + require_same_unit runtime). El ejemplo oficial se considera ilustrativo de forma, no ejecutable; las pruebas de paridad lo documentan y usan variantes unit-coherentes.
- `levelAtLeast` acepta `levels` (catálogo de niveles) además de `level`, como muestra §7/§2; si `levels` está presente, `level` debe pertenecer al catálogo (check semántico nuevo en validator).
- `policy.schema.json` NO necesita cambios: el `params` del stage es un objeto abierto por diseño (puerta de schema = estructura); los schemas de params por operador viven en `OperatorSpec.params_schema` y se validan con Draft202012Validator en la puerta semántica (additionalProperties:false en todos los niveles). Es el diseño documentado de dos puertas en validator.py.

## Work State
### Completed
- Implementación alineada con el contrato (operadores reescritos, condiciones unit-aware, refs de operador como aristas, validator ampliado, operatorData en trazas 1.1.0).
- Suites nuevas: `test_contract_parity.py`, `test_no_unhandled_exceptions.py`, `test_operator_specs.py`; legacy actualizadas a nuevas semánticas.
- Docs actualizadas: `C2-VERIFICATION-REPORT.md` (159 tests, iteración 3, sección "Paridad con el ejemplo oficial §2"), `C2-RUNBOOKS.md` (self-check).
- Verificación completa local: grade-policy.sh test 159 OK + E2E, publication-snapshot.sh test 119 OK + E2E, c0-test.sh 92 OK, c0-scan --tracked --strict BLOCK=0 REVIEW=0 (234 archivos), git diff --check limpio.
- **Commit + push**: `b49fbdc` en `feat/c2-grade-policy-engine` (29 archivos, +2574/−374; hook de scan PII BLOCK=0).
- **PR #5 body actualizado** vía `gh pr edit` con tabla de conformidad y nota sobre el ejemplo oficial §2.
- **CI remota verificada**: `gh pr checks 5` → c0/c1/c2 ×2 todos pass.

### Active
- (nada en curso; trabajo de la iteración 3 terminado y verificado)

### Blocked
- (ninguno conocido)

## Next Move
- Esperar feedback del review del PR #5. Si el reviewer pide ajustes (p. ej. sobre la resolución de la tensión del ejemplo oficial §2), abordarlos y volver a correr la verificación completa. Mantener el PR en Draft hasta decisión explícita.

## Relevant Files
- `engine/grade_policy/operators/base.py`: contrato OperatorSpec/OperatorReference ampliado.
- `engine/grade_policy/operators/*.py` (8): semánticas reescritas según contrato.
- `engine/grade_policy/conditions.py`: condiciones unit-aware + `levels` en levelAtLeast.
- `engine/grade_policy/validator.py`: puerta semántica ampliada + check level∈levels.
- `engine/grade_policy/graph.py`, `units.py`, `errors.py`, `models.py`, `engine.py`, `trace.py`, `schemas/traces-1.1.0.schema.json`.
- `engine/grade_policy/tests/test_contract_parity.py`, `test_no_unhandled_exceptions.py`, `test_operator_specs.py`: suites nuevas.
- `engine/grade_policy/tests/test_conformance.py` y demás tests: actualizados.
- `docs/implementation/C2-VERIFICATION-REPORT.md`, `C2-RUNBOOKS.md`: actualizados.
- `docs/implementation/C2-GRADE-POLICY-CONTRACT.md`: autoridad del contrato.
