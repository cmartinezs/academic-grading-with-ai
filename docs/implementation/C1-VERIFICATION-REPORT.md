# C1 — Reporte de verificación

Corte **C1 — Publication Snapshot y lifecycle**, branch
`feat/c1-publication-snapshot-lifecycle`. Incluye la corrección de los 55 hallazgos P0
del review de la fase 1 y la reparación residual final (serialización de compatibilidad
y lifecycle, aliases legacy atómicos con reemplazo vía CLI, contrato legacy exacto,
privacidad de excepciones en el origen, reconciliación por publicación y recuperación
de backups huérfanos de aliases).

## Base

- `master` actualizado a `2cf34a936f24af39d896a23e1769da3d89a3c653` (merge de C0).
- Línea base C0 previa: 92 tests OK; scan estricto `BLOCK=0 REVIEW=0` (148 archivos);
  `c0-status.sh` con roots temporales: `PASS`.
- Al inicio de la reparación final: C0 92 tests OK, C1 89 tests + E2E OK, scan estricto
  186 archivos `BLOCK=0 REVIEW=0`, árbol limpio, HEAD `4455e36`.

## Resultado

| Check | Resultado |
|---|---|
| C1 suite unittest (119 tests: contrato, integración, fallos, concurrencia, P0 hash, P0 privacy, P0 lifecycle, P0 compat, P0 recovery, compat final, aliases atómicos, privacidad de excepciones, consumer real, reconcile por publicación, serialización transición/compat, CLI replace-legacy-aliases, recuperación de backups huérfanos) | `OK` |
| C1 self-check E2E sintético (build → review → approve → published → compat → supersede) | `OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto (186 archivos) | `BLOCK=0 REVIEW=0` |
| `c0-status.sh` con roots temporales | `State: PASS` |
| Reproducibilidad (rebuild mismo epoch) | contentHash idéntico; `canonical/*` + `provenance/*` byte-idénticos |
| Reproducibilidad (epochs distintos) | contentHash y reviewHash idénticos (claves volátiles excluidas) |
| Review hash representativo (sintético) | `9b5d79e1dd733d4f134cff613e3a240579421f273fa97ea12806b0d1bb132152` |
| Concurrencia multiproceso | build vs build / approve vs approve / review vs approve / discard vs approve / generate vs generate / generate vs transición terminal / alias updates: sin archivos mixtos ni doble aprobación |
| Crash + reconciliación | snapshots promovidos se restauran de forma idempotente; nunca se eliminan; `reconcile` scoped a un `publicationId` |
| Compatibilidad | lock-first con staging único por operación; aliases legacy promovidos atómicamente; fallo deja cero archivos en el destino |
| Privacidad de excepciones | ningún mensaje de excepción ni stderr contiene RUT/email/rutas absolutas (incluido el CLI por subprocess) |
| Dependencia nueva | `jsonschema==4.10.3` pinneada en `engine/publication/requirements.txt` |
| CI remoto | `.github/workflows/c1.yml` ejecutado en el PR #4 (`gh pr checks` verde) |

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
  compatibility/reconcile/discard/test). Exit codes 0/1/2. Redacción de RUT/email/paths
  en stderr.
- Tests: `engine/publication/tests/test_c1.py` (119 tests, incluidos workers
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

## Reparación residual final

- **Serialización de compatibilidad**: `generate()` toma el lock por
  `(section, publication)` antes de inspeccionar/re-validar y lo mantiene para toda la
  operación; el staging es único por operación (`<operationId>`), solo se elimina staging
  propio y cada envelope debe coincidir con el `contentHash` del origen (gate de hash)
  antes de la promoción. Tests: dos `generate()` simultáneos (un ganador), generate vs
  transición terminal, crash pre/post rename, fallo de privacidad con cero archivos.
- **Aliases legacy atómicos**: el bundle completo (contenido exacto + `PROVENANCE.json`)
  se promueve con un único rename atómico; destino existente rechazado por defecto, y con
  reemplazo explícito el bundle actual va a un backup temporal con restauración en fallo y
  borrado solo tras fsync exitoso. Tests de inyección de fallo: crash al escribir el
  segundo archivo, crash pre-rename, crash post-backup-move (restaura byte-idéntico),
  crash post-promote (bundle nuevo completo), dos updates concurrentes serializados.
- **Contrato legacy exacto**: aliases con wrappers `{"items": [...]}` y claves
  contractuales (`studentId` opaco, `evaluationId`, `form`, `status`, `score`, `grade`,
  `resultPath` null explícito, `finalFeedback`, `ies`); `name`/`rut` vacíos; validador
  estructural que rechaza wrappers rotos o claves faltantes; consumer test que importa el
  consumidor real `sync-section-indexes.py` y demuestra que lee el alias sin cambios
  (cardinalidad, forms, estados, scores, grades, feedback y components equivalentes).
- **Privacidad de excepciones en el origen**: adapter/legacy/builder/compat/verify no emiten
  RUT (huella opaca SHA-256), ni paths absolutos, ni roots privados/state/temp en mensajes;
  los findings G6 referencian el archivo relativo sin reproducir el valor (el path absoluto
  ya no aparece en `GateError.details` ni en la excepción). El CLI `_redact()` queda como
  segunda línea de defensa (ahora también paths absolutos).
  Tests: `ExceptionPrivacyTest` cubre cada ruta pública, el finding G6 con path absoluto y el
  stderr del CLI por subprocess.
- **Reconciliación por publicación**: `reconcile(ctx, publication_id=None)` valida el id,
  errores claros para id inexistente, rechazo de id inválido y toca solo ese snapshot.
  Tests: sección con 3 snapshots donde solo el segundo se reconcilia; primero y tercero
  byte-idénticos y sin eventos nuevos; id inexistente/inválido; rerun idempotente.
- **Serialización lifecycle ↔ compatibilidad**: las transiciones de lifecycle
  (`published`, `superseded`, `corrected`, `revoked`) adquieren el lock por
  `(section, publication)` antes del lock de sección del ledger (orden publication →
  lifecycle) mediante `builder.transition`, el mismo lock que usa `compat.generate` y
  build/review/approve. Prueba multiproceso race generate vs `revoked` y vs `corrected`
  sobre la misma publicación (8 iteraciones por evento con reloj real): cuando gana la
  transición terminal, `generate` falla y no publica nada; cuando gana `generate`,
  las vistas se publican estrictamente antes del evento terminal (`generatedAt <= at`);
  se ejerce y comprueba ambos ordenamientos.
- **CLI `--replace-legacy-aliases`**: expuesto en `compatibility` y propagado a
  `compat.generate()`; se rechaza sin `--update-legacy-aliases` (exit 1 con mensaje
  claro). Tests CLI por subprocess: uso inválido, destino existente rechazado (sin
  staging residual) y reemplazo explícito exitoso que conserva el contrato legacy
  (`resultPath` null).
- **Recuperación de backups huérfanos de aliases**: cada reemplazo registra un marker
  `<operationId>.PENDING` junto al backup antes de mover el bundle actual; si el proceso
  aborta después de mover el alias al backup, `reconcile` detecta el backup huérfano
  bajo su lock de publicación y: alias ausente → restaura el bundle anterior
  (byte-idéntico), alias activo válido → conserva el alias y elimina el backup obsoleto
  (un alias activo válido nunca se sobrescribe), alias activo inválido → reporta y no
  toca nada. Tests: backup presente + alias ausente, y backup presente + alias activo;
  ambos idempotentes y con limpieza de staging/backups.

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
- `4455e36` docs: re-emit C1 verification report after all P0 gates pass
- `1e95885` fix(C1 compat): lock-first serialization, unique staging, hash gate
- `9eef81b` fix(C1 compat): atomic legacy alias bundle promotion
- `a197ccd` fix(C1 compat): exact legacy consumer contract for aliases
- `b8f2fbc` test(C1 compat/aliases): failure injection and concurrency coverage
- `c26cbc8` fix(C1 privacy): sanitize exceptions at source, never leak PII or paths
- `e11dd58` fix(C1 reconcile): scope reconciliation to a single publication
- `3268f68` docs(C1 final): contract/runbooks/verification report, inventory and PR body
- `b0e0d91` fix(C1 privacy): keep G6 path findings path-free at source
- `d6b7525` test(C1 compat): prove the real legacy consumer reads aliases unmodified
- `42774ea` docs(C1 final): CLI list includes reconcile; final 113-test verification
- `39c132d` fix(C1 lifecycle): serialize transitions with compat via the publication lock
- `8a43436` feat(C1 compat): expose --replace-legacy-aliases in the CLI
- `48d850e` fix(C1 compat): recover orphaned legacy-alias backups in reconcile

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
  permisos y eventos faltantes de forma idempotente y admite `--publication` para acotarlo.
- Ninguna excepción del motor publica PII ni rutas absolutas; el CLI redacta RUT/email/paths
  como segunda línea de defensa.
