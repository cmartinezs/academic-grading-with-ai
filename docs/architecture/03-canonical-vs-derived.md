# 03 — Fuentes canónicas y artefactos derivados

## Fuentes canónicas

| Fuente | Ruta | Rol |
|---|---|---|
| Roster | `evaluations/<SECTION>/students.json` | Base de estudiantes |
| Config de sección | `evaluations/<SECTION>/config.json` | Metadata + referencia a grade-rules |
| Evidencia humana | `evaluations/<SECTION>/<EV>/form-x/results/*.md` | Revisada; no es input de derivación |
| Resultados canónicos | `exports/publication-input/course/results.json` | **Fuente canónica máquina** |
| Reglas | `evaluations/<SECTION>/grade-rules.json` | Reglas declarativas (ADR-0004) |

## Artefactos derivados

| Artefacto | Generador | Consumidor |
|---|---|---|
| `evaluations/<SECTION>/grades.json` | `sync-section-indexes.py` | dashboard, discovery |
| `evaluations/<SECTION>/evaluations.json` | `sync-section-indexes.py` | índice de descubrimiento |
| `exports/relational-3fn/*` (tablas+vistas) | `export-relational-3fn.sh` | docente (consulta), portal (vista estudiante), directiva (BI) |
| `exports/student-results-web/*` | `build-student-results-web.sh` (Node opcional) | estudiantes (portal) |
| `exports/email/*` (destinatarios, estado, logs) | pipeline email (Node opcional) | estudiantes (con confirmación) |

Todos los artefactos son regenerables y deterministas a partir de la fuente canónica.
