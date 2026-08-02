# C1 — Publication Snapshot y lifecycle (plan de implementación)

Estado: aprobado para implementación. Rama: `feat/c1-publication-snapshot-lifecycle`.
Base: `master` (contiene C0 `2cf34a936f24af39d896a23e1769da3d89a3c653`).

Este corte implementa exclusivamente C1 del roadmap
[`04-roadmap.md`](../architecture/04-roadmap.md). C2–C7 quedan fuera de alcance.

## 1. Estado actual verificado

- C0 está fusionado en `master`: `2cf34a93` (merge de `feat/c0-security-data-boundaries`).
- `./scripts/c0-test.sh` → 92 tests OK.
- `./scripts/c0-scan.sh --tracked --strict` → `BLOCK=0 REVIEW=0` (148 archivos).
- `./scripts/c0-status.sh` con roots temporales owner-only → `State: PASS`.
- Working tree limpio antes de crear la rama.
- `python3` 3.12 con `jsonschema` 4.10.3 disponible (JSON Schema Draft 2020-12).

## 2. Mapa del export legacy

`export-publication-data.py` produce (ruta global `exports/publication-input/`):

| Archivo | Contenido |
|---|---|
| `manifest.json` | `generatedAt`, `schemaVersion`, `course` |
| `course/course.json` | metadata del curso + defaults (`approvalThreshold`, `grading`) |
| `course/students.json` | `items[]` con `id`, `name`, `rut`, `forms`, `summary` |
| `course/evaluations.json` | `items[]` con `id`, `title`, `type`, `date`, `weight`, `forms`, `summary`, `ieSummary`, `performanceLevels` |
| `course/results.json` | `items[]` con `studentId` (=rut), `evaluationId`, `form`, `status`, `score`, `grade`, `resultPath`, `finalFeedback`, `ies` |
| `course/course-summary.json` | agregado del curso completo |

`sync-section-indexes.py` consume `exports/publication-input/course/results.json` para
regenerar `evaluations/<SECTION>/grades.json` y `evaluations/<SECTION>/evaluations.json`.

`export-results.sh` encadena `sync → export → sync`.

## 3. Campos con PII

| Campo | Ubicación legacy | Acción en C1 |
|---|---|---|
| `rut` | `students.json`, `results.json`, `resultPath` | eliminado de contratos canónicos |
| `studentId` (legacy) | `results.json` = `str(rut)` | reemplazado por `studentId` opaco |
| `name` / `fullName` | `students.json`, `results.studentName` | eliminado de canonical; queda en store privado |
| `resultPath` | `results.json` (`evaluations/EV/form-*/results/<rut>.md`) | reemplazado por `evidenceRefs` opacos |
| `finalFeedback` | `results.json` | preservado como `feedback` permitido |
| `ies[].feedback` | `results.json` | preservado como componente (feedback permitido) |

## 4. Campos con identidad técnica incorrecta

| Campo | Problema | Corrección C1 |
|---|---|---|
| `studentId = str(rut)` | PII como clave técnica (ADR-0007) | `stu_<128 bits>` vía `c0.identity` |
| nombre de archivo `<rut>.md` | PII en rutas | `evidenceRefs` opacos |
| `order` | estable pero no universal | no se usa como clave |

## 5. Cálculos legacy que se preservan, no se rediseñan

- `percent_to_grade` (1.0–7.0, passing 60%).
- `weighted_average` (presentation percent).
- `summarize_scores` / `summarize_ies` / `summarize_performance_levels`.
- `build_students` (summary por estudiante: `averageScore`, `presentationPercent`,
  `presentationGrade`, etc.).

El adapter **no recalcula** notas: toma `score`, `grade`, `status`, `feedback` y `ies`
tal cual los emitió el export legacy y los congela en el snapshot. Las fórmulas anteriores
solo se reutilizan para regenerar vistas de compatibilidad y agregados derivados.

## 6. Consumidores de rutas actuales

| Ruta | Consumidor |
|---|---|
| `exports/publication-input/course/` | `sync-section-indexes.py`, publicación externa |
| `evaluations/<SECTION>/grades.json` | `workspace_status.py`, herramientas existentes |
| `evaluations/<SECTION>/evaluations.json` | `workspace_status.py`, navegación |
| `evaluations/<SECTION>/config.json` | `export-publication-data.py`, `sync-section-indexes.py`, `workspace_status.py` |
| `evaluations/<SECTION>/<EV>/plan.md` | `export-publication-data.py` (parseo de tablas) |

C1 no migra consumidores: `export-results.sh`, `sync-section-indexes.py` y la ruta global
continúan como flujo legacy. Los nuevos componentes consumen snapshots aprobados.

## 7. Contratos propuestos

Véase [`C1-SNAPSHOT-CONTRACT.md`](C1-SNAPSHOT-CONTRACT.md). Resumen:

- **Manifest**: identidad, estado, hashes, versiones, archivos declarados (path,
  clasificación, audiencia, size, sha256). Sin PII ni rutas absolutas.
- **Canonical**: `section.json`, `subjects.json`, `assessments.json`, `results.json`,
  `policy.json`.
- **Provenance**: `source-hashes.json`, `engine.json`, `migrations.json`.
- **Approvals**: `review.json`, `publication-approval.json` ligados al `contentHash` exacto.
- **Lifecycle ledger** (state root, append-only): `created`, `reviewed`, `approved`,
  `published`, `superseded`, `corrected`, `revoked`.

## 8. Árbol exacto del snapshot

```text
<publications-root>/sections/<sectionId>/<publicationId>/
├── manifest.json
├── canonical/
│   ├── section.json
│   ├── subjects.json
│   ├── assessments.json
│   ├── results.json
│   └── policy.json
├── provenance/
│   ├── source-hashes.json
│   ├── engine.json
│   └── migrations.json
└── approvals/
    ├── review.json
    └── publication-approval.json
```

C1 no materializa `projections/student`, `projections/teacher`, `projections/bi`,
`portal`, `email` ni `relational-3fn`. Reserva los nombres en schema/documentación.

## 9. State machine y transiciones

```text
created → reviewed → approved → published
                      ├──▶ superseded
                      ├──▶ corrected
                      └──▶ revoked
```

- `published` exige `receipt` (genérica; C1 no ejecuta publishers).
- `superseded` / `corrected` exigen `byPublicationId` (publicación existente y aprobada).
- `revoked` no elimina el snapshot.
- El estado actual se deriva del ledger append-only; nunca se modifica el snapshot.

## 10. Estrategia de staging/promoción

- Staging: `<temp-root>/publication-staging/<sectionId>/<publicationId>/`.
- Destino: `<publications-root>/sections/<sectionId>/<publicationId>/`.
- Precondición verificada antes de build: `st_dev` del staging root == `st_dev` del
  publications root (mismo filesystem, rename atómico). Si no se cumple → error con
  diagnóstico.
- Promoción: `fsync` de archivos y directorios, `os.rename` (nunca copy), `fsync` del
  padre, permisos read-only.
- Destino existente → rechazado.
- Crash pre-rename → solo staging recuperable. Crash post-rename → snapshot completo.
- Cleanup nunca elimina un snapshot aprobado.

## 11. Estrategia de hashes

- Una única escritura JSON determinista (UTF-8, `ensure_ascii=False`, claves ordenadas,
  indentación estable, newline final).
- `sha256` de cada archivo calculado sobre los bytes realmente escritos.
- `contentHash` = sha256 de la representación canónica (relpath → sha256) de
  `canonical/*` + `provenance/*`, excluyendo `manifest.json` y `approvals/*`.
- Metadata volátil (`createdAt`, `approvedAt`) no participa en `contentHash`.
- Clock inyectable; soporta `SOURCE_DATE_EPOCH`.

## 12. Estrategia de schema validation

- JSON Schema Draft 2020-12 mediante `jsonschema` (pinned).
- Cada archivo del snapshot se valida contra su schema por ruta relativa.
- Los gates G4/G5 combinan schema + invariantes semánticos (referencias, unicidad,
  corrección/supersesión). Fallo cerrado.

## 13. Compatibilidad old/new

- `export-results.sh`, `exports/publication-input/course/`,
  `evaluations/<SECTION>/grades.json` y `evaluations/<SECTION>/evaluations.json` se
  mantienen como flujo legacy, sin cambios por defecto.
- Vistas de compatibilidad nuevas se generan desde un snapshot aprobado solo con
  `compatibility --generate` (y `--update-legacy-aliases` explícito). Cada vista declara
  `sourcePublicationId`, `schemaVersion`, `generatedBy` y `canonicalSourceHash`.
- Comparación semántica old/new sobre fixture sintético (sección, estudiantes mapeados,
  evaluaciones, formas, statuses, scores, grades, feedback, IE/components, agregados).

## 14. Failure model

| Fallo | Resultado | Recuperación |
|---|---|---|
| Build fallido | sin snapshot parcial | descartar staging |
| Escritura falla durante staging | staging parcial, publications intacto | descartar staging |
| Crash pre-rename | staging recuperable | descartar staging |
| Destino existente | rechazo | elegir nuevo publicationId |
| Review con hash distinto | rechazo | rebuild/review |
| Cambio post-review | approval rechazado | nuevo review |
| Approval sin review | rechazo | revisar primero |
| Tampering post-aprobación | verify detecta hash/size | crear corrección |
| Transición inválida | rechazo | corregir comando |

## 15. Tasks incrementales

1. `engine/publication/` base (ids, jsonutil, clock, errors).
2. Schemas JSON versionados + validators.
3. Adapter legacy determinista.
4. Manifest, hashes y provenance.
5. Staging y promoción atómica.
6. Review/approval.
7. Lifecycle ledger.
8. Vistas de compatibilidad.
9. CLI + wrapper `scripts/publication-snapshot.sh`.
10. Tests (unit, contrato, integración, fallos, concurrencia).
11. CI `c1.yml`.
12. Docs (plan, contrato, runbooks, verificación) + actualización de índices.

## 16. Tests por task

| Task | Tests |
|---|---|
| ids | path traversal rechazado, publicationId único/inyectable, sectionId estable |
| schemas | válido, inválido, major version desconocida |
| adapter | mapping completo, estudiante sin mapping bloqueado, equivalencia semántica old/new |
| manifest | completo, archivo extra, hash incorrecto, size incorrecto, determinismo, locale, orden |
| staging | build fallido, write failure, crash pre-rename, destino existente |
| review/approve | review ligado a hash, cambio post-review, approval sin review, hash incorrecto |
| immutabilidad | tampering post-aprobación, rebuild rechazado, revocación no elimina |
| lifecycle | corrección nuevo id, corrects/supersedes válidos, exclusividad, transiciones inválidas, published con receipt, ledger concurrente |
| compat | vistas desde snapshot, declaran sourcePublicationId |
| legacy | export sigue funcionando, C0 tests verdes, scanner strict limpio |

## 17. Riesgos y decisiones

- Se usa `jsonschema` (ya instalado) pinneado en `engine/publication/requirements.txt`;
  se documenta como única dependencia nueva.
- `sectionId` = section code estructural (no PII), validado como segmento de path seguro.
- `assessmentId` = id de evaluación legacy (referencia estable, no PII).
- El ledger vive en state root, fuera del snapshot.
- Los aliases legacy solo se actualizan con flag explícito.
- No se versiona ningún snapshot real ni se usan datos reales en tests.

## 18. Fuera de alcance

- C2 Grade Policy Engine (no operadores, no expresión evaluable).
- C3 Email.
- C4 Portal.
- C5 Proyecciones teacher/3FN/BI.
- C6 Convenciones (solo documentación necesaria).
- C7 Discovery.
