# 04 — Roadmap, criterios de aceptación y riesgos

## Cortes

| Corte | Contenido | Depende de | Aceptación |
|---|---|---|---|
| **C1 Fundaciones** | Schemas (`results`, `grades`, `section-config`), validators como gates, ADR-0001/0002/0006/0007 | — | `export-results.sh` falla ante schema inválido; re-ejecución determinista byte a byte |
| **C2 3FN** | Port `export-relational-3fn.py` adaptado a `results.json` (no `.md`); schemas `bundle`/`bi`; validador; vistas BI con regla anti-fuga; wrapper | C1 | Mismo input → mismas tablas que el ref; vistas BI con cero PII; salida determinista |
| **C3 Portal** | Port `build-student-results-web.mjs` con fragmentos por estudiante + codes PBKDF2(250k); `publish`/`revoke`/`purge`; hosting checklist | C1 (y C2 si se usa la vista) | Estudiante ve solo sus datos; build idempotente; publish bloqueado sin hosting seguro |
| **C4 Email** | Port `automation/email/` + `build-student-email-recipients.sh` + `send-student-emails.sh`; estado por batch; dry-run default; entrega de link+código del portal | C1 | Dry-run no envía; `--send` solo a no-enviados; duplicados rechazados; cero PII en repo |
| **C5 Convenciones + secretos** | `support/` y `raw/` documentados; gitignore (`.env`, logs, web-dashboard, evidencia_drive); `.env.example`; CLAUDE.md opcional | independiente | `workspace-status.sh` valida convenciones; `git grep` no encuentra secretos |
| **C6 Discovery** | Scaffolding LLM que emite config candidata (grade-rules, forms, schemas) revisable | C1 | Borrador revisable; no entra al pipeline sin aprobación humana |

## Orden de entrega sugerido

`C1 → C2 → (C3 ‖ C4) → C5 → C6`

## Criterios de aceptación globales

- Reproducibilidad: mismo input → mismo output.
- Determinismo de todo publisher.
- Validación de schema en cada gate.
- Cero PII/secretos en git.
- Cada corte es reversible re-ejecutando el anterior.
- Ausencia de Node no rompe el core.

## Riesgos y rollback

| Riesgo | Mitigación | Rollback |
|---|---|---|
| Fuga de PII (portal/email) | Minimización (ADR-0007), hosting checklist | `revoke`/`purge` |
| Envío erróneo de email | Dry-run + confirmación + estado (ADR-0009) | Batch nuevo o `--force` controlado; log para notificar |
| Node ausente | Runtime check con error claro | Preview Python provisorio |
| Drift de schemas | Gates de validación (ADR-0006) | Re-generar artefactos desde `results.json` |
| Brute-force de códigos en hosting estático | Fragmentos por estudiante + PBKDF2(250k) + renovación de códigos | Rotación de códigos / `revoke` |
| Fuga por celdas pequeñas en BI | Supresión n < umbral en el validador | Re-generar vistas BI |
| Sobre-ingeniería | Alcance limitado a los 5 gaps genuinos | — |
| 3FN sin consumidor final | Modelo por audiencias (estudiantes/docente/directiva) definido | C2 puede diferirse; el core no depende de él |
