# Arquitectura — academic-grading-with-ai

Fase de diseño (sin código) para incorporar las capacidades genuinamente ausentes,
detectadas por la validación forense de `ANALYSIS_FPY1101_vs_BASE.md` contra el
repositorio de referencia `FPY1101-010V`.

## Estado

| Documento | Estado |
|---|---|
| [01-target-architecture.md](01-target-architecture.md) | Aprobado (diseño) |
| [02-data-flow.md](02-data-flow.md) | Aprobado (diseño) |
| [03-canonical-vs-derived.md](03-canonical-vs-derived.md) | Aprobado (diseño) |
| [04-roadmap.md](04-roadmap.md) | Aprobado (diseño) |
| [ADRs](ADRs/) | Propuestos (ADR-0001 a ADR-0010) |

## Línea base (premisas refutadas y descartadas)

- Cifras bytes/líneas incorrectas del informe original (p. ej. "73K líneas" de la SPA).
- "El base no tiene config.json por sección" → `scripts/init-course.sh` ya lo genera.
- "El base no genera grades.json/evaluations.json" → `sync-section-indexes.py` ya los genera.
- "Template de plan más simple" → `evaluation-plan-template.md` ya incluye esas secciones.
- "AVA import solo README" → `ava-import.mjs` es idéntico en base y ref.
- "Stubs de email en el base" → no existe ninguna automatización de email en el base.

## Capacidades genuinamente ausentes (objeto de este diseño)

1. Export relacional 3FN y su validador.
2. Automatización de email.
3. Portal web de resultados.
4. Schemas y reglas de calificación relacionadas.
5. Convenciones opcionales `support/`, `raw/` y `CLAUDE.md`.

## Principio central

La existencia de una capacidad en FPY1101-010V no implica copiarla. El repositorio
de referencia demuestra necesidades y soluciones experimentadas, pero este workspace
conserva una arquitectura genérica, mantenible y segura: la realidad de cada docente
vive en **datos** (`grade-rules.json`, `config.json`, schemas), nunca en código del core.
