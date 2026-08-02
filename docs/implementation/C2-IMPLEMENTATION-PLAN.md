# C2 — Grade Policy Engine (plan de implementación)

Estado: en implementación en `feat/c2-grade-policy-engine`.
Base: `master` (contiene C1 `cdf452222b8ef9cf72dc4ff70e112cfb553d606e`).

Este corte implementa exclusivamente C2 del roadmap
[`04-roadmap.md`](../architecture/04-roadmap.md). C3–C7 quedan fuera de alcance.

## 1. Estado post-C1 verificado

- `master` contiene C0 y C1; ambos commits de referencia son ancestros de HEAD:
  `cb56d282...`, `cdf452222b8...`.
- `./scripts/c0-test.sh` → 92 tests OK.
- `./scripts/publication-snapshot.sh test` → 119 tests OK + E2E OK.
- `./scripts/c0-scan.sh --tracked --strict` → `BLOCK=0 REVIEW=0` (186 archivos).
- `./scripts/c0-status.sh` con roots temporales → `State: PASS`.
- Working tree limpio antes de crear la rama.
- `python3` 3.12; `jsonschema==4.10.3` pinneada en `engine/publication/requirements.txt`.

## 2. Contratos C1 que no pueden romperse

1. `engine/publication/schemas/policy.schema.json` conserva su semántica
   (`mode: legacy-effective`, `calculationAuthority: legacy-export-adapter`).
2. Un snapshot C1 aprobado sigue verificándose sin migrarlo.
3. El builder C1 legacy (`build` sin `--grade-policy`) es byte-compatible con C1.
4. `canonical/results.json` conserva los resultados observados intactos.
5. Los hashes (`contentHash`/`reviewHash`) y el manifest de C1 siguen intactos para
   snapshots legacy.
6. `EXPECTED_FILE_META`, el registry de schemas y el verifier se extienden de forma
   aditiva: rutas nuevas se declaran explícitamente; rutas legacy no cambian.

## 3. Mapa de resultados observados frente a resultados calculados

| Dato | Fuente C1/canónica | Rol en C2 |
|---|---|---|
| `results[].score` | `canonical/results.json` | input normalizado (unidad `percent`/`points`) |
| `results[].status` | `canonical/results.json` | estado observado para condiciones `statusEquals` |
| `results[].grade` | `canonical/results.json` | nota observada; nunca se sobrescribe |
| `results[].components` | `canonical/results.json` | desglose observado (IE), conservado |
| outcome calculado | `canonical/outcomes.json` (nuevo) | salida del engine (nunca reescribe `results.json`) |
| trace calculado | `canonical/traces.json` (nuevo) | evidencia por stage, determinista |
| policy efectiva C2 | `canonical/policy.json` (mode `grade-policy-effective`) | autoridad de cálculo |

## 4. Autoridad de cada dato

| Dato | Fuente autoritativa | Consumer | Snapshot representation |
|---|---|---|---|
| estructura de evaluación | `section-config.json` | schema/validación | `canonical/section.json`, `canonical/assessments.json` |
| identidad opaca | `c0.identity` | engine/trace | `studentId` en `canonical/subjects.json` |
| pesos | `grade-policy.json` | engine | `canonical/policy.json` (mode C2) |
| resultado observado | export legacy | never overwritten | `canonical/results.json` |
| resultado calculado | `grade-policy-engine` | proyecciones | `canonical/outcomes.json` |
| trace | `grade-policy-engine` | auditoría | `canonical/traces.json` |

`engine/defaults.json` solo inicializa policies nuevas; nunca se consulta durante una
publicación (los defaults efectivos se materializan en la policy).

## 5. Modelo numérico y reglas de Decimal

- `Decimal(str(value))` es la única conversión de entrada; nunca `float` como autoridad.
- Contexto fijo `Decimal(prec=28, rounding=ROUND_HALF_EVEN)` aplicado con
  `decimal.localcontext` para aislar el estado global del intérprete.
- Porcentajes: valor numérico de porcentaje (`78.4` = 78.4%).
- Pesos: fracciones (`0.25` = 25%); suma igual a 1 dentro de
  `WEIGHT_SUM_TOLERANCE = Decimal("1e-9")`.
- Normalización de cero: `value.is_zero()`; el cero canónico se escribe `0`.
- Comparación: operadores Decimal nativos.
- Serialización: `decimal_str()` produce la representación decimal canónica (sin
  notación científica); en traces/outcomes se acompaña de `unit` y opcionalmente `scale`.
- Redondeo: solo en stages `round` explícitos; el modo se declara por stage
  (`halfUp`, `halfEven`, `floor`, `ceil`, `truncate`). Ningún redondeo implícito se
  aplica al serializar, comparar o convertir.
- Independencia de locale/timezone: ninguna operación usa locale ni reloj.

## 6. Unidades soportadas

- `percent`, `points`, `grade`, `scalar`, `level`.
- Todo valor procesado conoce su unidad; un operador rechaza unidades incompatibles.
- Conversiones solo vía `piecewiseLinearScale` explícito. Sin conversiones implícitas.

## 7. Catálogo exacto de operadores V1

| Operador | Fases | Unidad entrada | Unidad salida | missing policies permitidas |
|---|---|---|---|---|
| `weightedAverage` | normalization, aggregation | misma unidad | misma | fail, excludeAndRenormalize, zero, minimumOutput, pending, notApplicable |
| `sum` | normalization, aggregation | misma unidad | misma | fail, zero, minimumOutput, pending, notApplicable |
| `piecewiseLinearScale` | conversion | cualquier numérica | declarada | fail, zero, pending, notApplicable |
| `additiveBonus` | adjustment | target y source compatibles | target | fail, pending, notApplicable |
| `replaceLowestInput` | adjustment | target (weightedAverage) | target | fail, pending, notApplicable |
| `cap` | adjustment, finalization | target | target | fail, zero, pending, notApplicable |
| `floor` | adjustment, finalization | target | target | fail, zero, pending, notApplicable |
| `round` | finalization | target | target (conserva) | fail, pending, notApplicable |

## 8. Catálogo exacto de condiciones V1

| Condición | Fuente | Semántica |
|---|---|---|
| `statusEquals` | assessmentId | `status == valor` |
| `levelAtLeast` | assessmentId (unit level) | `level >= umbral` |
| `assessmentPresent` | assessmentId | el input está presente |
| `assessmentMissing` | assessmentId | el input está ausente |
| `scoreAtLeast` | assessmentId | `value >= umbral` |
| `scoreBelow` | assessmentId | `value < umbral` |

Cada condición devuelve `(bool, reason)` y aparece en el trace. Fallan cerrado si falta
información requerida. No hay AND/OR arbitrarios en V1.

## 9. Fases y orden global

```text
normalization → aggregation → adjustment → conversion → finalization
```

Dentro de una fase: orden topológico estable por dependencias (ver §10). Un stage no
puede depender de una fase posterior. La salida final la declara `resultStageId`.

## 10. Modelo del DAG

- `stageId` únicos; referencias a assessments y a stageIds existentes.
- Sin ciclos, sin self-references, sin referencias a fases posteriores.
- Planificador determinista: nodos = stages, aristas = dependencias de input; orden
  topológico con desempate lexicográfico por `stageId` para grafos equivalentes.
- Detección de ciclos con reporte sanitizado (stageIds lógicos, sin datos académicos).

## 11. Missing policies

Semántica por operador (tabla en §7). Reglas globales:

- `pending` produce outcome no finalizable (`status: pending`, `finalizable: false`).
- `notApplicable` no equivale a cero; produce `notApplicable` en el trace.
- `excludeAndRenormalize` solo aplica en `weightedAverage` (renormalización de pesos).
- `minimumOutput` requiere escala o valor mínimo resoluble; sin `minimum` en params
  falla la validación.
- Toda decisión de missing aparece en el trace.

## 12. Contrato del trace

Ver `C2-GRADE-POLICY-CONTRACT.md` §7. El trace por estudiante declara
`traceSchemaVersion`, `policyId`, `policyVersion`, `policyHash`, `engineVersion`,
`subjectId` opaco, `resultStageId` y `stages[]` con decisiones y warnings. Una regla no
aplicada también aparece con motivo. Sin RUT, nombre, email, rutas privadas, evidence
content ni secretos.

## 13. Política de schema versioning

- Contratos C2 propios: `policy` (schema 1.0.0), `outcomes` (1.0.0), `traces` (1.0.0).
- El verificador selecciona schema por versión declarada (`schemaVersion`) y por `mode`
  para `canonical/policy.json` (`legacy-effective` → schema C1; `grade-policy-effective`
  → schema C2).
- Major desconocida falla cerrado; minor compatible sigue reglas explícitas (additivo).
- No existe fallback silencioso al schema más reciente; las migraciones son explícitas.

## 14. Integración con Publication Snapshot

- `build --grade-policy <file>`: camino C2.
- Flujo: parse legacy/reviewed results → canonical observed inputs → load policy exacta
  → schema validation → semantic validation → calculate outcomes → emit traces →
  snapshot complete effective policy → hash de artefactos lógicos → review/approve C1.
- `canonical/policy.json` en mode `grade-policy-effective` incluye la policy completa;
  `policyHash` sobre bytes canónicos; `engineVersion` registrado.
- `canonical/outcomes.json` y `canonical/traces.json` quedan cubiertos por
  `manifest.files`/`contentHash`/`reviewHash`.
- Un fallo de policy no deja staging parcial. Snapshots legacy-effective continúan
  verificándose sin cambios.
- `--replace-legacy-aliases` y `compatibility` no se ven afectados.

## 15. Compatibilidad legacy-effective

- El camino legacy (sin `--grade-policy`) es byte-compatible.
- Los schemas C1 no cambian; el verifier extiende (aditivo) la selección de schema y el
  chequeo semántico según `mode`.
- `EXPECTED_FILE_META` gana `canonical/outcomes.json` y `canonical/traces.json`.
- No se convierte automáticamente una policy legacy a C2: solo con
  `--grade-policy` explícito y si la semántica se demuestra; una migración incompleta se
  detiene y reporta la regla no representable.

## 16. Estrategia de fixtures

Todos los fixtures son sintéticos (ver §18 del contrato y la sección de conformidad
FPY1101). Cero PII; identificadores ficticios. Se crean en
`engine/grade_policy/fixtures/` y se referencian desde los tests.

## 17. Estrategia de conformidad FPY1101

- Se usan únicamente reglas verificadas en este repositorio:
  `weighted_average` y `percent_to_grade` de `export-publication-data.py` y los defaults
  de `engine/defaults.json` (`minGrade 1`, `passingGrade 4`, `maxGrade 7`,
  `passingPercent 60`, `presentationWeight 60`, `examWeight 40`).
- Los comportamientos PCT/EvG se modelan como `additiveBonus` con cap y
  `replaceLowestInput` con condición `levelAtLeast`, y se documentan como equivalentes
  a la referencia sanizada.
- Fixtures con valores de referencia calculados por fórmula; una diferencia de nota,
  score, cap o redondeo bloquea C2.

## 18. Failure model

| Fallo | Resultado | Recuperación |
|---|---|---|
| schema inválido | error tipado | corregir policy |
| operador desconocido | fallo cerrado | corregir policy |
| condición desconocida | fallo cerrado | corregir policy |
| ciclo en DAG | fallo cerrado | corregir policy |
| unidad incompatible | fallo cerrado | corregir policy |
| assessment faltante | missingPolicy | policy/inputs |
| disco lleno al escribir outputs | staging parcial, sin promote | reintentar |
| crash antes de promote | sin snapshot parcial | reintentar |
| policy cambiada tras review | approval rechazado | nuevo review |
| engine version cambiada tras review | approval rechazado | nuevo review |
| outcome/trace tampered | verify falla | crear corrección |
| snapshot legacy C1 | sigue verificándose | — |

## 19. Riesgos

- Modificación aditiva del verifier C1: mitigado con tests de regresión C1 completos.
- Semántica PCT/EvG documentada de forma parcial en la referencia: los fixtures se
  limitan a lo verificado y marcan los supuestos para confirmación humana.
- Complejidad del DAG/Decimal: propiedad de determinismo y golden tests.

## 20. Fuera de alcance

- C3 Email.
- C4 Portal.
- C5 Proyecciones teacher/3FN/BI.
- C6 Convenciones.
- C7 Discovery.
- No se implementa lógica específica de FPY1101, Duoc ni otra institución.
