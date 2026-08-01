# C1 — Reporte de verificación

Corte **C1 — Publication Snapshot y lifecycle**, branch
`feat/c1-publication-snapshot-lifecycle`. Incluye la corrección de los 55 hallazgos P0
del review de la fase 1.

## Base

- `master` actualizado a `2cf34a936f24af39d896a23e1769da3d89a3c653` (merge de C0).
- Línea base C0 previa: 92 tests OK; scan estricto `BLOCK=0 REVIEW=0` (148 archivos);
  `c0-status.sh` con roots temporales: `PASS`.

## Resultado

| Check | Resultado |
|---|---|
| C1 suite unittest (89 tests: contrato, integración, fallos, concurrencia, P0 hash, P0 privacy, P0 lifecycle, P0 compat, P0 recovery) | `OK` |
| C1 self-check E2E sintético (build → review → approve → published → compat → supersede) | `OK` |
| Smoke E2E (`/tmp/opencode/c1-smoke`, incl. reconciliación y aliases legacy con `PROVENANCE.json`) | `SMOKE OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto (186 archivos) | `BLOCK=0 REVIEW=0` |
| `c0-status.sh` con roots temporales | `State: PASS` |
| Reproducibilidad (rebuild mismo epoch) | contentHash idéntico; `canonical/*` + `provenance/*` byte-idénticos |
| Reproducibilidad (epochs distintos) | contentHash y reviewHash idénticos (claves volátiles excluidas) |
| Concurrencia multiproceso | build vs build / approve vs approve / review vs approve / discard vs approve: sin archivos mixtos ni doble aprobación |
| Crash + reconciliación | snapshots promovidos se restauran de forma idempotente; nunca se eliminan |
| Dependencia nueva | `jsonschema==4.10.3` pinneada en `engine/publication/requirements.txt` |

## Alcance implementado

- `engine/publication/` (package 0.1.0): `ids`, `jsonutil` (volatile-key stripping,
  hashing normalizado), `clock`, `errors`, `schemas` + `schemas/*.schema.json`
  (Draft 2020-12), `legacy`, `adapter`, `hashing` (per-file sha256 + `contentHash` +
  `reviewHash` + `EXPECTED_FILE_META`), `verify` (G4–G9), `builder` (G0–G3 + staging +
  promoción atómica + review/approve ligado al hash + `reconcile`), `lifecycle`
  (estados estrictos, `published` como recibo, validación profunda de referencias),
  `locking` (`SnapshotLock` con recuperación de stale-PID), `compat` (vistas +
  aliases legacy con sidecar `PROVENANCE.json`).
- CLI `engine/scripts/publication_snapshot.py` y wrapper
  `scripts/publication-snapshot.sh` (build/verify/review/approve/status/transition/
  compatibility/reconcile/discard/test). Exit codes 0/1/2. Redacción de RUT/email en stderr.
- Tests: `engine/publication/tests/test_c1.py` (89 tests, incluidos workers
  multiproceso) + runner `engine/scripts/publication_snapshot_test.py`.
- CI `.github/workflows/c1.yml` (tests/E2E, regresión C0, scan estricto).
- Docs: plan, contrato, runbooks; README, STRUCTURE_INVENTORY,
  `docs/architecture/README.md`, `engine/docs/export-publication.md`.

## Gates

- G0 boundary/identidad, G1 config/evaluaciones, G2 mapping completo, G3 adapter,
  G4 contract (schemas), G5 semantic (ids únicos, refs, statuses, exclusividad
  corrects/supersedes), G6 privacy (PII/secrets/keys/paths absolutos/nombres de roster
  en texto libre), G7 manifest (files, sizes, hashes, contentHash y reviewHash
  reproducibles + cross-check de approvals), G8 lifecycle (approvals, inmutabilidad
  read-only, estados estrictos), G9 classification por archivo (per-path
  classification/audience). Todas fall-cerrado.

## Cobertura P0 (55 hallazgos)

- **Hashes (1–9)**: per-file sha256; `contentHash` sobre canónico + provenance estable
  sin claves volátiles (`generatedAt`/`builtAt`); `reviewHash` liga contentHash al núcleo
  inmutable del manifest + clasificación/audiencia/hash por archivo; aprobaciones firman
  el reviewHash; manifest/review/publication-approval cross-validados.
- **Concurrencia (10–14)**: lock por `(section, publication)` serializa
  build/review/approve/discard; stale-lock recovery por PID; multiprocess sin archivos
  mixtos, sin doble aprobación, sin staging perdido.
- **Lifecycle (15–23)**: lock antes de read+validate; `nonexistent` ≠ `created`;
  `created` duplicado rechazado; validación completa del ledger antes de append;
  actor obligatorio no-email sanitizado; `published` como recibo sin cambio académico;
  `byPublicationId != publicationId` + callback de validación profunda; `--confirm approve`.
- **Privacidad (24–31)**: RUT/email enmascarados en stderr CLI; detección de paths
  absolutos POSIX/Windows/UNC/`file://` (G6); nombres de roster bloqueados en texto libre
  de `canonical/results.json` (token >= 4); clasificación per-path por G9.
- **Adapter/equivalencia (32–37)**: `form` por resultado y `term` por sección
  preservados; `evidenceRefs` siempre `[]`; schema `results` con solo los campos
  requeridos (studentId/assessmentId/attemptId/status/components).
- **Compatibilidad (38–48)**: `generate()` verifica el snapshot aprobado completo,
  bloquea revoked/superseded/corrected, staging bajo temp root + gates de schema/privacy,
  promoción atómica con `check_same_filesystem`, rechazo de sobrescritura; aliases legacy
  exactos con sidecar `PROVENANCE.json`; consumer test de equivalencia.
- **Recuperación (49–51)**: crash states pre/post rename/chmod/append; reconciliación
  idempotente; nunca se elimina un snapshot promovido.
- **CLI/docs (52–55)**: `--supersedes-publication`/`--corrects-publication` en build;
  `--review-hash` (+ `--content-hash` opcional) en review/approve; `--actor`/
  `--by-publication`/`--confirm approve` en transition; contrato, runbooks, ADR-0001/
  0006/0011 y este reporte actualizados.

## Conformidad con ADRs

Cumple ADR-0001 (snapshots inmutables, reconciliación sin borrado), ADR-0006
(snapshots/section namespace; claves volátiles excluidas del hash lógico) y
ADR-0011 (estados estrictos con `nonexistent`, `published` como recibo, validación
profunda de referencias); el flujo legacy sigue intacto.

## Commits

- `d345753` docs: define C1 snapshot implementation plan (+ contrato)
- `0054be8` feat: add versioned publication schemas and validators
- `6c95964` feat: add deterministic legacy snapshot adapter
- `85a8be3` feat: add manifest hashing and provenance gates
- `e6164c9` feat: add staging, atomic promotion, review/approve and lifecycle ledger
- `ea862eb` feat: add snapshot compatibility views
- `7060dfc` feat: add C1 publication snapshot CLI and wrapper
- `33e93da` test: add C1 contract integration and failure coverage
- `40189c7` ci: add C1 publication snapshot gates
- `65648c7` fix(P0 hashes): per-file sha256, contentHash/reviewHash layers, classification
- `9934580` fix(P0 concurrency): per-section-publication lock, stale-lock recovery
- `cb70a82` fix(P0 lifecycle): lock-before-read, strict states, receipts separated
- `31627a9` fix(P0 compat): verify source, block revoked, atomic staging, alias sidecar
- `1a7afa6` fix(P0 recovery): crash states, idempotent reconciliation, never delete
- `d8bee56` docs(P0 cli/runbooks): reconcile CLI command, contract/runbooks/ADRs updated

## Observaciones

- `provenance/engine.json` queda excluido del `contentHash` lógico (invariante 13:
  metadata volátil no contamina el hash), aunque sigue protegido por `manifest.files`.
- El scanner requiere allowlist para RUT/emails sintéticos de los tests C1
  (`engine/c0/allowlist.json`); los secretos reales no son allowlistables.
- Un build fallido nunca deja un snapshot parcial bajo `ACADGRAD_PUBLICATIONS_ROOT`;
  los residuos de staging se descartan con `discard`.
- La generación de compatibilidad verifica el snapshot aprobado antes de escribir y
  falla cerrado si el origen está revocado/superseded/corregido; un fallo deja cero
  archivos en el destino.
- Los snapshots promovidos nunca se eliminan para simular rollback; `reconcile` restaura
  permisos y eventos faltantes de forma idempotente.
