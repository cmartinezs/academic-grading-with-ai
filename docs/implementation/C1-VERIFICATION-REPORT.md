# C1 — Reporte de verificación

Corte **C1 — Publication Snapshot y lifecycle**, branch
`feat/c1-publication-snapshot-lifecycle`.

## Base

- `master` actualizado a `2cf34a936f24af39d896a23e1769da3d89a3c653` (merge de C0).
- Línea base C0 previa: 92 tests OK; scan estricto `BLOCK=0 REVIEW=0` (148 archivos);
  `c0-status.sh` con roots temporales: `PASS`.

## Resultado

| Check | Resultado |
|---|---|
| C1 suite unittest (48 tests: contrato, integración, fallos, concurrencia) | `OK` |
| C1 self-check E2E sintético (build → review → approve → published → compat) | `OK` |
| Regresión C0 (92 tests) | `OK` |
| Scan tracked estricto (182 archivos) | `BLOCK=0 REVIEW=0` |
| `c0-status.sh` con roots temporales | `State: PASS` |
| Reproducibilidad (rebuild mismo epoch) | contentHash idéntico; `canonical/*` + `provenance/*` byte-idénticos |
| Reproducibilidad (epochs distintos) | contentHash idéntico (metadata volátil excluida, invariante 13) |
| Dependencia nueva | `jsonschema==4.10.3` pinneada en `engine/publication/requirements.txt` |

## Alcance implementado

- `engine/publication/` (package 0.1.0): `ids`, `jsonutil`, `clock`, `errors`,
  `schemas` + `schemas/*.schema.json` (Draft 2020-12), `legacy`, `adapter`,
  `verify` (gates G4–G8), `builder` (G0–G3 + staging + promoción atómica +
  review/approve), `lifecycle` (ledger append-only), `compat` (vistas).
- CLI `engine/scripts/publication_snapshot.py` y wrapper
  `scripts/publication-snapshot.sh` (build/verify/review/approve/status/
  transition/compatibility/discard/test). Exit codes 0/1/2.
- Tests: `engine/publication/tests/test_c1.py` + runner
  `engine/scripts/publication_snapshot_test.py`.
- CI `.github/workflows/c1.yml` (tests/E2E, regresión C0, scan estricto).
- Docs: plan, contrato, runbooks; README, STRUCTURE_INVENTORY,
  `docs/architecture/README.md`, `engine/docs/export-publication.md`.

## Gates

- G0 boundary/identidad, G1 config/evaluaciones, G2 mapping completo, G3 adapter,
  G4 contract (schemas), G5 semantic (ids únicos, refs, statuses, exclusividad
  corrects/supersedes), G6 privacy (PII/secrets/keys/absolute paths), G7 manifest
  (files, sizes, hashes, contentHash reproducible), G8 lifecycle (approvals,
  inmutabilidad read-only). Todas fall-cerrado.

## Conformidad con ADRs

Cumple ADR-0001 (datos fuera del repo), ADR-0006 (snapshots/section namespace) y
ADR-0011 (vistas derivadas de snapshots aprobados); el flujo legacy sigue intacto.

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
- docs: runbooks y reporte (este documento)

Nota: el plan y el contrato se commitean juntos en `d345753` (desviación menor de la
secuencia sugerida, que separaba ambos docs).

## Observaciones

- `provenance/engine.json` queda excluido del `contentHash` lógico (invariante 13:
  metadata volátil no contamina el hash), aunque sigue protegido por `manifest.files`.
- El scanner requiere allowlist para RUT/emails sintéticos de los tests C1
  (`engine/c0/allowlist.json`); los secretos reales no son allowlistables.
- Un build fallido nunca deja un snapshot parcial bajo `ACADGRAD_PUBLICATIONS_ROOT`;
  los residuos de staging se descartan con `discard`.
