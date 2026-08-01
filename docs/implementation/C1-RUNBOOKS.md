# C1 — Runbooks operativos

Operaciones de snapshot de publicación y lifecycle para el corte C1.
Todos los comandos usan `./scripts/publication-snapshot.sh`.

## Exit codes

- `0` éxito.
- `1` error de uso / estado inválido (por ejemplo, transición ilegal).
- `2` fallo de gate (schema, hash, identidad, privacidad) — fail-closed.

## Variables de entorno

`ACADGRAD_PRIVATE_ROOT`, `ACADGRAD_STATE_ROOT`, `ACADGRAD_PUBLICATIONS_ROOT`,
`ACADGRAD_TEMP_ROOT` (resueltas por `engine/c0/paths.py`). `SOURCE_DATE_EPOCH`
fija timestamps reproducibles en builds. `SECTION_CODE` selecciona la sección.

## Flujo normal (build → review → approve)

```bash
export SECTION_CODE=FP2111-S1
./scripts/export-results.sh                      # regenera exports/publication-input/

# 1. build: genera staging + manifest + contentHash + reviewHash (imprime ambos)
./scripts/publication-snapshot.sh --section "$SECTION_CODE" build

# 2. review: liga la revisión al reviewHash exacto (el build imprime ReviewHash)
RH=<reviewHash-impreso-por-build>
./scripts/publication-snapshot.sh --section "$SECTION_CODE" verify --target staging
./scripts/publication-snapshot.sh --section "$SECTION_CODE" review --review-hash "$RH" --reviewer reviewer-a

# 3. approve: promueve de forma atómica (requiere confirmación explícita)
./scripts/publication-snapshot.sh --section "$SECTION_CODE" approve --review-hash "$RH" --approver approver-a --confirm approve

# 4. publicar y generar vistas de compatibilidad
./scripts/publication-snapshot.sh --section "$SECTION_CODE" transition --event published --actor ops --receipt <REF>
./scripts/publication-snapshot.sh --section "$SECTION_CODE" compatibility --update-legacy-aliases
```

Para recuperar el `reviewHash` de un staging ya construido:

```bash
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['reviewHash'])" \
  "<TEMP_ROOT>/publication-staging/$SECTION_CODE/<PUB_ID>/manifest.json"
```

`--content-hash` es opcional en `review`/`approve` como comprobación cruzada adicional.

## Verificación

```bash
./scripts/publication-snapshot.sh --section "$SECTION_CODE" verify --target staging   # draft en staging
./scripts/publication-snapshot.sh --section "$SECTION_CODE" verify --target approved  # snapshot publicado
./scripts/publication-snapshot.sh --section "$SECTION_CODE" status                     # ledger + snapshots
```

## Corrección

1. Aprobar el snapshot actualizado con `correctsPublicationId` (nuevo id).
2. Registrar el evento terminal sobre el snapshot anterior:

```bash
./scripts/publication-snapshot.sh --section "$SECTION_CODE" --publication <OLD_PUB> \
  transition --event corrected --actor ops --by-publication <NEW_PUB> --reason "corrección" --confirm approve
```

La corrección nunca muta el snapshot aprobado: crea un `publicationId` nuevo y
deja un evento en el ledger append-only.

## Fallos y recuperación

| Fallo | Señal | Recuperación |
|---|---|---|
| Build fallido | exit `2`, sin snapshot en publications | `discard` del staging |
| Escritura falla en staging | staging parcial, publications intacto | `discard` del staging |
| Crash pre-rename | staging recuperable | `discard` del staging |
| Crash post-rename / pre-`approved` | snapshot promovido con eventos faltantes | `reconcile` |
| Destino existente | exit `1` `DestinationExistsError` | nuevo `publicationId` |
| Review con hash distinto | exit `2` `ReviewHashMismatchError` | rebuild/review |
| Cambio post-review | exit `2` al aprobar | nuevo review |
| Approval sin review | exit `1` `NotReviewedError` | revisar primero |
| Tampering post-aprobación | `verify --target approved` falla | crear corrección |
| Transición inválida | exit `1` `InvalidTransitionError` | corregir comando |

Recuperación de crash post-promoción (idempotente; nunca elimina un snapshot promovido):

```bash
./scripts/publication-snapshot.sh --section "$SECTION_CODE" --publication <PUB_ID> reconcile
```

`reconcile` restaura permisos read-only en snapshots promovidos con permisos de
escritura y añade los eventos académicos faltantes en el ledger; volver a ejecutarlo
no produce cambios. Los fallos de integridad se reportan sin borrar el snapshot.

Con `--publication <PUB_ID>` la reconciliación se limita a un único snapshot: un
`publicationId` inexistente es un error de estado claro y un id inválido se rechaza
antes de escanear; ningún otro snapshot de la sección se lee ni se modifica. Sin
el flag se reconcilia toda la sección.

Discard de staging:

```bash
./scripts/publication-snapshot.sh --section "$SECTION_CODE" --publication <PUB_ID> discard
```

## Self-check

```bash
./scripts/publication-snapshot.sh test
```

Ejecuta la suite unittest de C1 (contrato, integración, fallos, concurrencia) y un
escenario E2E sintético (build → review → approve → published → compat).
