# 01 — Arquitectura objetivo

Fase: diseño. No se implementa código en esta fase.

## Resolución previa (A–J)

### A. Fuente canónica de resultados

Doble capa:

- `evaluations/<SECTION>/<EV>/form-x/results/*.md` → **evidencia humana** (revisada).
- `exports/publication-input/course/results.json` → **fuente canónica máquina**; única
  entrada permitida para todo artefacto derivado.

Ningún publisher re-parsea `.md`; eso solo lo hace `export-publication-data.py`. Se
elimina la duplicación de parsing que existe en el ref (donde el export 3FN vuelve a
parsear `.md`).

### B. Modelo canónico de publicación

Tres contratos versionados:

1. `evaluations/<SECTION>/config.json` — enriquecido: course, access, evaluations con
   forms/pesos/fechas/tipos + referencia a reglas.
2. `exports/publication-input/course/results.json` — resultados parseados con IEs.
3. `evaluations/<SECTION>/grades.json` — nota consolidada por estudiante/EV (vista estable).

`evaluations.json` es un índice derivado, no una fuente.

### C. Artefactos derivados

`grades.json`, `evaluations.json`, `exports/relational-3fn/`, `exports/student-results-web/`,
`exports/email/`. Todos regenerables y deterministas a partir de la fuente canónica.

### D. Límites core / automation / adapters / publishers

```text
┌──────────────────────────────────────────────────────────────────┐
│ discovery/        (NO determinista, opcional)                     │
│  scaffolding LLM → config candidata (grade-rules, forms, schemas) │
│  salida SIEMPRE aprobada por humano → se vuelve config determinista│
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│ core/  (determinista, Python, sin estado)                        │
│  adapters   → extract-submissions, import-students, AVA import   │
│  parsing    → export-publication-data.py → results.json          │
│  engine     → aplica grade-rules.json (declarativo, por sección) │
│  schemas    → engine/schemas/*.schema.json (versionados)         │
│  validators → gates en cada corte de pipeline                    │
└──────┬──────────────────────────┬───────────────────────────────┘
       │                          │
┌──────▼──────────────┐   ┌───────▼──────────────────────────────┐
│ publishers Python   │   │ publishers Node (OPCIONAL, aislados) │
│ sync-section-       │   │ build-student-results-web.mjs        │
│ indexes (grades/    │   │ automation/email/* (nodemailer)      │
│ evaluations)        │   │ runtime check → skip con error claro │
│ export-relational   │   └──────────────────────────────────────┘
│ 3fn + validador     │
└─────────────────────┘
```

### E. Node.js opcional

Core en Python (existente). Node solo en los publishers email/portal, reutilizando
código ya probado del ref (versiones pinneadas). Cada wrapper verifica la
disponibilidad del runtime y falla con mensaje claro sin romper el core.

### F. Versionamiento y compatibilidad de schemas

`schemaVersion` en todo contrato canónico. SemVer: minor retrocompatible; major exige
paso de migración o archivo nuevo. La validación de schema es un **gate obligatorio**:
el pipeline falla, no advierte.

### G. Protección PII y secretos

Por defecto mínimo: RUT truncado/hasheado en artefactos públicos, sin emails ni
feedback en el portal salvo configuración explícita, `.env` gitignored (con
`.env.example`), logs de email sin cuerpos ni destinatarios completos.
`evidencia_drive/` y submissions quedan fuera del repo por gitignore.

### H. Idempotencia, auditoría y confirmación de envíos

Email con dry-run por defecto, confirmación humana por batch, estado por batch que
salta ya-enviados, log CSV con messageId. Export/publishers deterministas
(mismo input → mismo output byte a byte).

### I. Seguridad del portal

Aislamiento por **fragmentos por estudiante** (nunca dataset global servible), acceso
por **códigos PBKDF2(250k)** en hosting estático. `publish` bloqueado si no hay hosting
seguro configurado.

### J. Papel del modelo relacional 3FN

Modelo de información **derivado** (nunca canónico) que informa a tres audiencias:

```text
canonical results.json
        │  export-relational-3fn.sh (determinista)
        ▼
┌─ TABLAS TRANSACCIONALES (25) ── uso interno, PII, nunca públicas
│   source_documents, evaluation_results, student_grade_adjustments,
│   student_grade_components, grade_calculation_runs, students, evaluations, IEs
│
├─ VISTAS DE CONSULTA ── docente
│   distribuciones por nivel/forma/EV, revisión de feedback, desglose NP/ET/bonos
│
├─ VISTA ESTUDIANTE ── portal
│   student_portal.json → fragmento por estudiante, solo datos propios
│
└─ VISTAS BI ── directiva/institucional (SOLO agregados, sin PII)
    course_summary, performance_level_distribution, section_averages,
    bonus_impact, missing_submissions, comparativas por forma/sección
```

Regla anti-fuga BI: celdas con n < umbral se suprimen. La directiva nunca recibe datos
a nivel de estudiante individual; el docente sí (es su sección).

## Decisiones (D1–D12)

| # | Decisión | Alternativas | Recomendación |
|---|---|---|---|
| D1 | Fuente canónica | .md único / **results.json + .md como evidencia** / grades.json único | results.json como fuente máquina |
| D2 | Modelo de publicación | anidado results.json / flat + índices / relacional canónico | results.json + grades.json (vista estable) + índices |
| D3 | Papel 3FN | contrato central / **modelo de información derivado (3 audiencias)** / solo vistas | proyección derivada, no canónica |
| D4 | Reglas de calificación | hardcoded / **declarativas grade-rules.json** / mixto | declarativas (data-driven, cualquier docente) |
| D5 | Runtime publishers | todo Python / **Node para email+portal (reuso)** / reescribir | Node opcional, gate por disponibilidad |
| D6 | Versionado schemas | sin versionar / **semver + gates** / doble schema | semver + validación obligatoria |
| D7 | PII | completa / **mínima por defecto** / config por artefacto | mínima + opt-in explícito |
| D8 | Envío email | directo / **dry-run default + confirmación** | dry-run default + confirmación por batch |
| D9 | Portal | dataset global / **fragmentos por estudiante + codes** / hosting auth obligatorio | fragmentos + codes PBKDF2 en hosting estático |
| D10 | Convenciones support/raw | impuestas / **documentadas opcionales** / omitidas | opcionales, validadas por workspace-status |
| D11 | AVA adapter | ya idéntico, tocar / **congelar** | congelar (no es gap) |
| D12 | Discovery no determinista | fusionado al core / **capa separada, humana-gate** | capa separada; output aprobado → config determinista |

## Email: contrato de diseño

- **Entrada**: `{studentId, rut(masked), name, email, evId, form}` desde `--from-roster`
  o CSV de `build-student-email-recipients.sh` (join roster + grades). Filtro opt-in,
  dedupe por `studentId`.
- **Destinatarios**: `exports/email/recipients-<batch>.csv` revisable antes de enviar.
- **Dry-run (default)**: previews HTML en `exports/email/preview-<batch>/`, resumen con
  emails enmascarados (`j***@***.com`).
- **Confirmación**: envío requiere `--send --batch <id>` + prompt con conteo. SMTP real
  con credenciales en `.env` gitignored.
- **Idempotencia**: estado `exports/email/state/<batch>.json` con messageId por estudiante;
  re-ejecutar salta ya-enviados; `--force` solo re-envía explícito.
- **Duplicados**: dedupe por `(studentId, batchId, email)` + log global que rechaza el
  mismo EV dentro de una ventana configurable (default 7 días).
- **Auditoría**: `exports/email/logs/send-log-<batch>.csv` con estudiante enmascarado,
  messageId, status, timestamp, intento. Sin cuerpos.
- **Reintentos**: por destinatario, 2 reintentos con backoff (2s, 5s); el batch continúa;
  error SMTP de conexión → retry del batch.
- **Errores**: try/catch por destinatario (nunca aborta el batch); plantilla inválida →
  fail-fast en dry-run.
- **PII**: cuerpos solo con nombre + resultados propios; estado/logs gitignored.
- **Pruebas**: unit tests de `lib/` (puerto del ref), dry-run con transporte JSON de
  nodemailer, golden-file de plantillas, test de estado que previene duplicados.

## Portal: diseño

- **Aislamiento**: un fragmento HTML/JSON por estudiante; el directorio de salida NO
  contiene dataset global. Sin código → solo el fragmento del portador es visible.
- **Estático**: el hosting sirve exactamente el contenido de
  `exports/student-results-web/`.
- **Autenticación**: códigos PBKDF2(250k) que desbloquean el fragmento propio. Los
  códigos/enlaces se entregan por el pipeline de email.
- **Publicación/revocación**: `publish` copia al destino configurado y exige flag
  explícito; `revoke` borra o rota; `purge` aplica retención. Sin `PORTAL_BASE_URL`
  https configurada → publish falla.
- **Retención**: últimas N builds (default 5), `purge` elimina las antiguas.
- **Comparativas permitidas**: solo agregados de curso (promedio/min/max) y comparación
  del estudiante vs promedio. Prohibido ranking que revele identidades.
- **Dataset**: score, nota, componentes EV1–EV4, NP/ET, bonos, desglose de IEs
  (niveles/puntos), feedback solo si el docente lo habilita.
- **Estándar vs hosting**: el workspace define el contrato de build y los gates; el
  hosting provee TLS/control de acceso. Se documenta una *hosting checklist*.
