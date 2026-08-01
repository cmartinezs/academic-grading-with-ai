# C0 — Plan de implementación (Threat model, PII, identidad y límites de almacenamiento)

Estado: aprobado para implementación (ADR-0001 a ADR-0011 aprobados el 2026-08-01).
Rama: `feat/c0-security-data-boundaries`.
Base: `master` (merge de arquitectura `b536fa4509a90c5565ff4086b5a3e2c4571bbeb3`).

## 1. Estado actual verificado

- El repositorio es un workspace starter: `evaluations/` y `exports/` solo contienen
  `.gitkeep`; no existen secciones ni datos reales versionados.
- `git ls-files` confirma 100 archivos tracked, todos de configuración, scripts,
  templates, onboarding sintético y documentación.
- `.gitignore` ya excluye `runtime/private`, `runtime/publications`, `runtime/state`,
  `evaluations/*/students.json`, `evaluations/*/*/students.json`,
  `evaluations/*/*/assignments.json`, `evaluations/*/*/form-*/results/`,
  `exports/*`, `automation/ava/config.json`, `**/*.log`, `**/*.lock` y `.env*`.
- No existe infraestructura de tests ni `pyproject`/`setup.py`; se usará `unittest`
  (stdlib) sin dependencias nuevas.
- Los scripts actuales usan `evaluations/<SECTION>/students.json` como roster,
  `students.json`/`assignments.json` por evaluación, resultados en
  `form-*/results/<rut>.md`, e índices de compatibilidad `evaluations.json`/`grades.json`
  vía `sync-section-indexes.py`.
- `workspace_status.py` diagnostica secciones, evaluaciones y forms usando `rut` como
  clave de identidad (p. ej. `result_ruts_from_paths` y `duplicate_values(..., "rut")`).
- `sync-section-indexes.py` genera `assignments.json` con `studentId = str(rut)`.
- `students_csv_to_json.py` importa roster desde CSV manteniendo `rut` como clave.

## 2. Rutas que contienen o pueden contener PII

| Ruta | Contenido | Clasificación actual |
|---|---|---|
| `evaluations/<SECTION>/students.json` | roster: RUT, nombres, email/github, avaUser | RESTRICTED (ignorada) |
| `evaluations/<SECTION>/<EV>/students.json` | roster efectivo | RESTRICTED (ignorada) |
| `evaluations/<SECTION>/<EV>/assignments.json` | asignaciones por rut | RESTRICTED (ignorada) |
| `evaluations/<SECTION>/<EV>/form-*/results/*.md` | resultados individuales | RESTRICTED (ignorada) |
| `evaluations/<SECTION>/<EV>/form-*/submissions/*` | entregas | RESTRICTED (ignorada) |
| `evaluations/<SECTION>/grades.json` | notas | RESTRICTED (ignorada) |
| `exports/publication-input/*` | export privado | RESTRICTED (ignorada) |
| `automation/ava/config.json` | credenciales/sesión AVA | RESTRICTED (ignorada) |
| `runtime/private`, `runtime/state`, `runtime/publications` | raíces objetivo | RESTRICTED (ignoradas) |

## 3. Flujos que leen o escriben información privada

1. `init-course.sh` → `students_csv_to_json.py` → `evaluations/<SECTION>/students.json`.
2. `sync-section-indexes.py` → `assignments.json`, `evaluations.json`, `grades.json`.
3. `assign_forms.py` → roster efectivo y asignaciones por evaluación.
4. `prepare_evaluation.py` → estructura de evaluación (plantillas).
5. `extract-submissions.sh` → `form-*/submissions/`.
6. `review-batch.sh` / `review-student.sh` → resultados `form-*/results/<rut>.md`.
7. `export-publication-data.py` → `exports/publication-input/course/*.json`.
8. `workspace_status.py` → diagnóstico (solo lectura, reporta rut en mensajes).
9. `automation/ava/ava-import.mjs` → sesión AVA privada.

## 4. Identificadores actuales y sus riesgos

| Identificador | Uso actual | Riesgo |
|---|---|---|
| `rut` | clave en roster, assignments, resultados, índices | PII usada como clave técnica; contradice ADR-0007 |
| `studentId` (en `assignments.json`) | `str(rut)` | identidad opaca falsa; derivada de PII |
| nombre de archivo de resultado | `<rut>.md` | PII en nombres de archivo |
| `order` | orden de roster | estable pero no universal |
| `avaUser` | login AVA | PII/institucional; solo en área privada |

Riesgo transversal: cualquier copy/commit de `evaluations/<SECTION>/` expone RUT, nombres
y resultados.

## 5. Compatibilidad que debe conservarse

- El flujo actual (`init-course`, `add_evaluation`, `prepare-evaluation`, `assign-forms`,
  `extract-submissions`, `review-batch`, `export-results`) debe seguir funcionando sin
  configuración nueva durante la transición.
- `evaluations/<SECTION>/students.json` y `evaluations/<SECTION>/<EV>/students.json`
  permanecen como estructura legacy hasta migrar.
- `workspace_status.py` conserva su reporte actual; se le agregan gates C0 sin cambiar
  sus contratos de salida.
- Onboarding sintético funcional (`onboarding/`) intacto.

## 6. Diseño propuesto

### 6.1 Raíces de runtime

```text
<private-root>/
└── sections/<section-id>/
    ├── roster/
    ├── submissions/
    ├── evidence/
    └── results/

<state-root>/
├── identity/
├── locks/
├── migrations/
└── diagnostics/

<publications-root>/        # reservada para C1
<temp-root>/                # datos temporales de build
```

- Ubicación configurable por variable de entorno y archivo `runtime.json`.
- Default seguro fuera del repositorio: `$XDG_DATA_HOME/academic-grading-with-ai`
  (o `~/.local/share/academic-grading-with-ai`).
- Fallback dentro del repo (`runtime/`) solo si está completamente ignorado por Git;
  en caso contrario, error fail-closed.
- Resolución centralizada en `engine/c0/paths.py`; siempre rutas absolutas.

### 6.2 Clasificación de datos

`engine/c0/classification.py` define `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`
y el predicado `is_versionable(cls)`. Mapeo mínimo según ADR-0007 y
`05-security-and-data-boundaries.md`.

### 6.3 Identidad opaca

`engine/c0/identity.py`:

- `studentId = "stu_" + token aleatorio (128 bits)`; nunca derivado de RUT/nombre/email.
- Store privado en `<state-root>/identity/identity.json` con mapping
  `externalIdentifiers -> studentId` + display name + contact.
- `ensure()` idempotente; detección de duplicados y conflictos; dry-run.
- Logs sin PII (solo `studentId`).

### 6.4 Migración compatible

`engine/c0/migration.py`:

- Detecta secciones (`evaluations/*/config.json`), genera plan y copia a
  `<private-root>/sections/<section>/` (roster convertido con `studentId`, resultados
  renombrados a `<studentId>.md`, entregas/evidencia copiadas por hash).
- Dry-run por defecto; `--apply` explícito; no borra origen; verifica hashes; escribe
  manifest y ledger (`<state-root>/migrations/`) sin PII; idempotente; detecta
  migraciones parciales; `--rollback` técnico de archivos copiados; deja instrucciones
  para eliminación manual.

### 6.5 Scanner de PII y secretos

`engine/c0/scanner.py` + `engine/c0/allowlist.json`:

- Detecta secretos por patrón de asignación, bloques de claves privadas, tokens
  comunes, `.env` reales, emails en dominios no reservados, RUT chileno con guion en
  zonas versionables, y rutas privadas (submissions, results, roster, capabilities,
  estado operacional, previews/logs de email).
- Allow-list explícita y versionada para fixtures sintéticos y ejemplos.
- Valores enmascarados (nunca impresos completos).
- `engine/scripts/c0_scan.py` soporta `--tracked`, `--staged`, `--path`.

### 6.6 Gates y workspace status

`engine/c0/status.py` + integración en `workspace_status.py`:

- Checks: private root, state root, zonas inseguras, archivos privados versionables,
  identificadores faltantes/duplicados, migraciones pendientes, permisos, secretos,
  artefactos privados en zonas públicas, compatibilidad legacy, configuración incompleta.
- Estados `PASS`/`WARN`/`FAIL`; PII/secretos → `FAIL`; comando read-only; exit code
  no cero ante `FAIL`.

### 6.7 Fixtures sintéticos

`engine/c0/fixtures/synthetic/`:

- Roster, secciones múltiples, casos válidos/inválidos, colisiones, faltantes, rutas
  inseguras, muestras de PII/secretos, migración. Dominios reservados (`example.test`),
  identificadores opacos; cero datos reales.

## 7. Tareas incrementales

1. Paquete `engine/c0` + `paths.py` + `classification.py`. — hecho
2. `identity.py` + CLI `c0_identity.py`. — hecho
3. `migration.py` + CLI `c0_migrate.py`. — hecho
4. `scanner.py` + allow-list + CLI `c0_scan.py` + hook pre-commit opcional. — hecho
5. `status.py` + CLI `c0_status.py` + integración en `workspace_status.py`. — hecho
6. Fixtures sintéticos completos. — hecho
7. Threat models y runbooks (`docs/implementation/`). — hecho
8. Verificación final y reporte. — pendiente

## 8. Tests por tarea

| Tarea | Tests |
|---|---|
| Rutas | resolución; private root fuera del repo; rechazo de raíz insegura; fallback local ignorado; rutas con espacios y Unicode |
| Clasificación | mapeo de clases; versionalidad |
| Identidad | generación; estabilidad; no derivación de PII; duplicados; conflictos; persistencia |
| Migración | dry-run; aplicada; idempotencia; parcial; hashes; rollback; no borrado de origen; ledger sin PII |
| Scanner | secretos; emails; RUT sintético; allow-list; enmascaramiento; exit codes |
| Status | PASS; WARN; FAIL; exit codes; read-only |
| Fixtures | onboarding funcional; working tree sin datos privados; concurrencia/locking |

## 9. Riesgos

- Falsos positivos del scanner en documentación con ejemplos; mitigado con dominios
  reservados y allow-list explícita.
- `git check-ignore` depende de un repositorio Git válido; sin Git se falla cerrado.
- Migración de resultados por renombrado `<rut>.md` → `<studentId>.md` no reescribe
  contenido; la equivalencia se verifica por hash y se conserva el mapping.
- El modo legacy convive temporalmente; se retirará en cortes posteriores (ADR-0001).

## 10. Criterios de aceptación

- ADR aprobados registrados.
- Separación real de private/state/publications.
- Identidad opaca funcional y persistente.
- Migración dry-run, idempotente, sin borrado de origen y con rollback técnico.
- Scanner funcional con allow-list y enmascaramiento.
- `workspace-status` fail-closed ante PII/secretos.
- Fixtures 100% sintéticos.
- Tests pasando; onboarding intacto; sin PII nueva en Git.
- Rama publicada y Draft PR creado contra `master`.

## 11. Fuera de alcance

- C1 Publication Snapshot (no se crean snapshots).
- C2 Grade Policy Engine.
- C3 Email (prepare/approve/execute).
- C4 Portal seguro.
- C5 Proyecciones 3FN/BI.
- C6 Convenciones `support/`/`raw/`/`CLAUDE.md`.
- C7 Discovery con LLM.
