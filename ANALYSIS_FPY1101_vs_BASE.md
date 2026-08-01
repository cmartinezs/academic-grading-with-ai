# Análisis Comparativo: FPY1101-010V vs academic-grading-with-ai

**Fecha:** 2026-07-31
**Autor:** Arquitecto de Software / Analista de Repositorios
**Repositorio base:** `academic-grading-with-ai` (estándar objetivo)
**Repositorio referencia:** `../FPY1101-010V` (curso real con adaptaciones)

---

## 1. Resumen Ejecutivo (10 puntos)

1. **FPY1101-010V tiene 4 exportaciones avanzadas** (publicación, relacional-3FN, web dashboard estudiantil, email automatizado) que el repositorio base no tiene; son las mejoras de mayor impacto productivo.

2. **Relational-3FN export** (`engine/scripts/export-relational-3fn.py:1-1004`) modela 33 tablas normalizadas con trazabilidad completa fuente→resultado→ajuste→nota final; incluye validación automática (`validate-relational-3fn-export.py`) y vistas para portal estudiantil.

3. **Student-results-web** (`engine/scripts/build-student-results-web.mjs:73K líneas`) genera SPA estática navegable por alumno con desglose EV/NP/ET, ajustes PCT/EvG, rúbrica localizada, y dashboard comparativo.

4. **Email automation** (`automation/email/`) usa Node.js + Nodemailer con plantillas, placeholders validados, dry-run, logs CSV, y tests unitarios; el repo base solo tiene stubs vacíos.

5. **config.json en sección** (`evaluations/FPY1101-010V/config.json:1-146`) define metadata completa del curso, evaluaciones, formas, pesos, fechas y tipos (regular/voluntary); el base usa `defaults.json` + plantillas sin config por sección.

6. **grades.json** (`evaluations/FPY1101-010V/grades.json:1-1136`) persiste resultados estructurados con IEs desglosados, feedback, nivel, puntos, score y grade por estudiante/forma; el base no tiene archivo equivalente.

7. **Support/ folder por EV** (`evidencia_drive/`, `support/original-submissions/`, `support/scripts/`) organiza trazabilidad de descargas AVA, entregas originales, y scripts de recalibración; el base no contempla esto.

8. **evaluations.json consolidado** (`evaluations/FPY1101-010V/evaluations.json`) metadata de todas las EV para descubrimiento rápido; el base dispersa esto en `config.json`.

9. **Plan.md operativo rico** (strategy, parallel review, action log, follow-up) (`EV1/plan.md:1-5342`) es estado vivo, no solo lista de estudiantes; el template base es más simple.

10. **AVA import automation** (`automation/ava/ava-import.mjs:32K líneas`) conecta con AVA para sincronizar entregas/calificaciones; experimental, acoplado a DUOC, no generalizable sin adaptación.

---

## 2. Matriz de Capacidades

| ID | Capacidad | Evidencia en referencia | Estado en base | Valor | Generalizable | Riesgo | Recomendación |
|----|-----------|-------------------------|----------------|-------|---------------|--------|---------------|
| C01 | Export relacional 3FN (33 tablas) | `engine/scripts/export-relational-3fn.py:1-1004`, `exports/relational-3fn/tables/*.json` | Solo `export-publication-data.py` simple | **Muy alto**: trazabilidad completa, auditoría, BI | **Alta**: modelo genérico curso/sección/EV/forma/estudiante | Medio: complejidad, mantenimiento schemas | **Adoptar** (adaptar schemas a `engine/schemas/`) |
| C02 | Validación export 3FN | `engine/scripts/validate-relational-3fn-export.py:1-161` | No existe | **Alto**: garantiza integridad referencial | **Alta**: reglas de negocio parametrizables | Bajo | **Adoptar** |
| C03 | Portal web resultados estudiantil (SPA) | `engine/scripts/build-student-results-web.mjs`, `exports/student-results-web/public/*` | No existe | **Muy alto**: auto-servicio alumno, transparencia | **Alta**: datos vienen de export 3FN/views | Medio: generar HTML/JS estático grande | **Adoptar** (como script opcional en `engine/scripts/`) |
| C04 | Email automatizado con plantillas | `automation/email/send-student-emails.mjs`, `lib/*.mjs`, `templates/`, `tests/` | Stub `scripts/send-student-emails.sh` (7 líneas) | **Alto**: notificación masiva trazable, dry-run | **Alta**: CSV + plantilla + SMTP genéricos | Bajo: credenciales en `.env` | **Adoptar** (mover a `engine/automation/email/`) |
| C05 | config.json por sección (metadata completa) | `evaluations/FPY1101-010V/config.json:1-146` | Solo `defaults.json` en `engine/` | **Alto**: una fuente de verdad por curso | **Alta**: schema versionado, extensible | Bajo | **Adoptar** (añadir a `init-course.sh`) |
| C06 | grades.json por sección (resultados persistidos) | `evaluations/FPY1101-010V/grades.json:1-1136` | No existe (solo `results/` por forma) | **Alto**: consulta rápida, histórico, export feeding | **Alta**: estructura normalizada por IE | Medio: duplicación con `results/` | **Adoptar** (generar desde `results/` en export) |
| C07 | evaluations.json consolidado | `evaluations/FPY1101-010V/evaluations.json:1-126` | Disperso en `config.json` | **Medio**: descubrimiento rápido EV | **Alta**: derivable de `config.json` | Bajo | **Adoptar** (generar en `sync-section-indexes.py`) |
| C08 | Support folder (original-submissions, scripts, evidence_drive) | `evaluations/FPY1101-010V/EV3/support/`, `evidencia_drive/` | No contemplado | **Medio**: trazabilidad descarga AVA, reprocesamiento | **Media**: depende de flujo AVA específico | Medio: acoplamiento a LMS | **Adaptar** (documentar patrón, no imponer) |
| C09 | Plan.md operativo rico (strategy, parallel, action log) | `evaluations/FPY1101-010V/EV1/plan.md:1-5342` | Template básico (`review-plan-template.md`) | **Alto**: estado vivo, coordinación, auditoría | **Alta**: plantilla mejorada reutilizable | Bajo | **Adoptar** (mejorar template) |
| C10 | AVA import automation | `automation/ava/ava-import.mjs:32K`, `config.json` | Solo `automation/ava/` (README, UPGRADE-PLAN) | **Medio-Alto**: sincroniza LMS↔workspace | **Baja**: API DUOC específica, auth, session | **Alto**: credenciales, mantenimiento, breaking changes | **Postergar** (documentar como patrón, no incluir) |
| C11 | student-results-web build script (Node.js) | `engine/scripts/build-student-results-web.mjs:73K` | Solo Python scripts | **Alto**: genera SPA completa | **Media**: requiere Node, output grande | Medio: dependencia Node en engine | **Adaptar** (opcional, documentar requisito Node) |
| C12 | Relational 3FN schemas (JSON Schema) | `engine/schemas/relational-3fn/*.json` | No existe | **Alto**: contratos de datos, validación CI | **Alta**: versionado, evolutivo | Bajo | **Adoptar** (añadir a `engine/schemas/`) |
| C13 | PCT/EvG bonus rules codificados | `export-relational-3fn.py:349-371`, `733-781` | No existe | **Alto**: reglas de negocio explícitas, auditables | **Media**: reglas específicas DUOC | Medio: hardcoded en script | **Adaptar** (externalizar a `config/grade-rules.json`) |
| C14 | Localización niveles desempeño (EN→ES) | `export-relational-3fn.py:1051-1067` | Solo inglés en templates | **Medio**: UX portal alumno | **Alta**: mapa configurable | Bajo | **Adoptar** (añadir a `defaults.json`) |
| C15 | Onboarding guide idéntica en ambos | `onboarding/guide.md` (igual) | Idéntica | **N/A** | **N/A** | **N/A** | **Sin cambios** |
| C16 | `.claude/settings.local.json` (permisos históricos) | `.claude/settings.local.json:97 líneas` | No existe | **Bajo**: solo historial de sesión | **Ninguna**: específico a sesión | **Alto**: fuga de rutas, credenciales implícitas | **Descartar** (no migrar, limpiar) |
| C17 | `evidencia_drive/` (29 subdirs) | `evidencia_drive/` | No existe | **Bajo**: backup local AVA | **Baja**: acoplado a curso | **Alto**: datos alumnos, PII, duplicación | **Descartar** (no migrar, documentar exclusión) |
| C18 | `raw/` folder con briefs, roster source, informe | `evaluations/FPY1101-010V/raw/` | No existe | **Medio**: trazabilidad fuentes originales | **Media**: patrón documentable | Bajo | **Adaptar** (documentar convención `raw/`) |
| C19 | AGENTS.md menciona web-dashboard legacy | `AGENTS.md:8` | AGENTS.md no lo menciona | **Bajo**: solo documentación | **N/A** | **N/A** | **Adoptar** (actualizar AGENTS.md base) |
| C20 | CLAUDE.md con convención `apoyo/` y `forma-x/` | `CLAUDE.md:11` | No existe `CLAUDE.md` | **Medio**: guía para agentes IA | **Alta**: convenciones reutilizables | Bajo | **Adoptar** (crear `CLAUDE.md` base) |
| C21 | `scripts/export-relational-3fn.sh` wrapper | `scripts/export-relational-3fn.sh:11 líneas` | No existe | **Bajo**: entry point consistente | **Alta**: patrón wrapper estándar | Bajo | **Adoptar** (añadir a `scripts/`) |
| C22 | `scripts/validate-relational-3fn.sh` wrapper | `scripts/validate-relational-3fn.sh:11 líneas` | No existe | **Bajo**: entry point consistente | **Alta** | Bajo | **Adoptar** |
| C23 | `scripts/build-student-results-web.sh` wrapper | `scripts/build-student-results-web.sh:6 líneas` | No existe | **Bajo** | **Alta** | Bajo | **Adoptar** |
| C24 | `scripts/build-student-email-recipients.sh` | `scripts/build-student-email-recipients.sh:7 líneas` | No existe | **Bajo** | **Alta** | Bajo | **Adoptar** |
| C25 | `scripts/send-student-emails.sh` wrapper | `scripts/send-student-emails.sh:7 líneas` | `scripts/send-student-emails.sh` (stub 169B) | **Medio**: entry point real | **Alta** | Bajo | **Adoptar** (reemplazar stub) |
| C26 | `.agents/` vacío | `.agents/` (vacío) | No existe | **N/A** | **N/A** | **N/A** | **Ignorar** |
| C27 | `.codex/` vacío | `.codex/` (vacío) | No existe | **N/A** | **N/A** | **N/A** | **Ignorar** |
| C28 | `.idea/` (IDE config) | `.idea/` | No existe | **N/A**: config local IDE | **N/A** | **N/A** | **Descartar** |

### Leyenda de Clasificación

- **Mejora generalizable**: C01, C02, C03, C04, C05, C06, C07, C09, C12, C14, C19, C20, C21, C22, C23, C24, C25
- **Configuración específica del curso**: C08, C13, C18
- **Automatización reutilizable**: C01, C02, C03, C04, C11
- **Documentación reutilizable**: C09, C19, C20
- **Duplicación**: C06 (grades.json duplicando results/), C07 (evaluations.json derivable de config.json)
- **Deuda técnica**: C10 (AVA import acoplado, sin tests, credenciales), C16 (settings.local.json con secretos implícitos)
- **Experimento**: C10, C11 (Node.js en engine Python)
- **Riesgo de seguridad o privacidad**: C16, C17 (PII en evidencia_drive, support/original-submissions)
- **Diferencia sin valor funcional**: C26, C27, C28

---

## 3. Elementos que NO deben migrarse

| Elemento | Razones |
|----------|---------|
| `.claude/settings.local.json` | Contiene historial de permisos de sesión específica con rutas absolutas, credenciales implícitas, comandos ad-hoc; cero valor reutilizable, riesgo de fuga. |
| `evidencia_drive/` (29 carpetas) | Backup local de descargas AVA con datos de alumnos (PII), duplicación de `submissions/`, acoplado a curso específico. |
| `automation/ava/` (`ava-import.mjs` 32K líneas) | Acoplado a API DUOC/AVA, requiere credenciales, session handling, mantenimiento activo; patrón documentable pero código no portable. |
| `.idea/` | Configuración local de IDE (IntelliJ), irrelevante para el workspace estándar. |
| `grades.json` **como archivo fuente** | En FPY1101-010V se mantiene manualmente duplicando `results/`; en el estándar debe ser **generado** desde `results/` durante export, no editado a mano. |
| `evaluations.json` **como archivo fuente** | Igual: derivable de `config.json`, no fuente primaria. |
| `raw/` con contenido específico del curso | El patrón `raw/` es útil (documentar en AGENTS.md), pero el contenido (briefs, roster source, informe) es específico del curso. |
| `support/original-submissions/` con archivos reales | Contiene entregas reales de alumnos (PII); el patrón `support/` es útil, el contenido no. |
| `support/scripts/recalibrate_ev3.py` | Script ad-hoc para recalibrar una EV específica; no generalizable. |
| `automation/ava/.ava-session/` | Directorio de sesión/cache de automatización AVA, irrelevante. |
| `automation/ava/reports/` | Reportes de ejecuciones pasadas, específicos al curso. |

---

## 4. Mejoras presentes parcialmente en el repositorio base

| Capacidad | Estado en base | Qué falta para paridad |
|-----------|----------------|------------------------|
| Export publication (JSON normalizado) | ✅ Completo (`export-publication-data.py`:820 líneas) | Falta: generar `grades.json`, `evaluations.json`, relational-3FN, student-results-web |
| `prepare_evaluation.py` (templates, plan.md, assignments) | ✅ Completo (489 líneas, usa templates) | Falta: `merge_students` más robusto, `case.md` desde template |
| `assign_forms.py` | ✅ Completo (6975 líneas) | Paridad alcanzada |
| `review-student.sh` | ✅ Idéntico (1400 bytes) | Paridad alcanzada |
| `sync-section-indexes.py` | ✅ Completo (5299 líneas) | Falta: generar `evaluations.json` consolidado |
| `init-course.sh` / `import-students.sh` | ✅ Funcionales | Falta: crear `config.json` por sección (no solo `defaults.json`) |
| Templates (result, plan, base, case, assignments) | ✅ Completos | Falta: mejorar `plan-template` con strategy/parallel/action-log/follow-up |
| `AGENTS.md` / `AGENTS.es.md` | ✅ Completos | Falta: mencionar web-dashboard legacy, `exports/student-results-web`, `exports/relational-3fn` |
| Onboarding guide | ✅ Idéntica | Paridad alcanzada |
| Engine scripts structure | ✅ Python + templates | Falta: añadir Node.js scripts opcionales, schemas JSON, `automation/email` |

---

## 5. Decisiones que requieren validación humana

### D1: ¿Incluir Node.js en el engine para scripts de email y student-results-web?

- **Opción A**: Mantener todo en Python; reimplementar email y web export en Python.
  - ✅ Ventajas: Un solo runtime, coherencia, menor superficie de ataque.
  - ❌ Desventajas: `build-student-results-web.mjs` son 73K líneas (SPA completa), reescribir costoso; email automation ya tiene tests y madurez en Node.
- **Opción B** (Recomendada): Añadir Node.js como dependencia opcional documentada; mantener scripts Node en `engine/automation/` separados del core Python.
  - ✅ Ventajas: Reutiliza código probado, email ya tiene tests, web export genera SPA completa.
  - ❌ Desventajas: Dos runtimes, requiere documentar `package.json` en `engine/automation/email/` y `engine/automation/web/`.
- **Opción C**: Solo email en Node (maduro, 11 archivos lib + tests), web export en Python (generar JSON + plantilla HTML simple).
  - ✅ Ventajas: Email es crítico y listo; web export se simplifica.
  - ❌ Desventajas: Pierde la SPA rica actual (dashboard, desglose, localización).

**Pregunta concreta**: ¿Aceptas añadir Node.js como dependencia opcional del workspace para `engine/automation/email/` y `engine/scripts/build-student-results-web.mjs`, documentando requisitos en README y AGENTS.md?

---

### D2: ¿Externalizar reglas de nota (PCT, EvG, ponderaciones) a configuración declarativa?

- **Opción A** (Recomendada): Crear `engine/config/grade-rules.json` con reglas parametrizadas; `export-relational-3fn.py` y `export-publication-data.py` lo lean.
  - ✅ Ventajas: Reglas auditables, versionables, separadas del código; permite cursos con políticas distintas.
  - ❌ Desventajas: Complejidad inicial, migrar lógica hardcoded (`export-relational-3fn.py:349-371`, `733-781`).
- **Opción B**: Mantener hardcoded en scripts Python; documentar que son políticas DUOC 2026.
  - ✅ Ventajas: Simple, funciona hoy.
  - ❌ Desventajas: Cambio de política = cambio de código; no portable a otras instituciones.

**Pregunta concreta**: ¿Externalizamos las reglas de cálculo de nota (ponderaciones EV, bonos PCT, beneficio EvG, redondeo, nota mínima) a `engine/config/grade-rules.json` versionado, o las mantenemos hardcoded en los scripts de export?

---

### D3: ¿Estructura de `support/` por EV como estándar documentado?

- **Opción A** (Recomendada): Documentar en AGENTS.md la convención `evaluations/<SECTION>/<EV>/support/` con subcarpetas opcionales: `original-submissions/`, `scripts/`, `additional-considerations.md`. No crear por defecto.
  - ✅ Ventajas: Flexible, documenta patrón real sin imponer estructura vacía.
  - ❌ Desventajas: Menos discoverable.
- **Opción B**: Crear `support/` vacía en `prepare-evaluation.py` con `.gitkeep`.
  - ✅ Ventajas: Estructura visible, discoverable.
  - ❌ Desventajas: Ruido en repos nuevos, carpetas vacías.

**Pregunta concreta**: ¿Documentamos el patrón `support/` en AGENTS.md como convención opcional (sin crearlo por defecto), o lo creamos vacío en `prepare-evaluation.py`?

---

### D4: ¿Migrar `config.json` por sección al estándar (reemplazar/extender `defaults.json`)?

- **Opción A** (Recomendada): `init-course.sh` cree `evaluations/<SECTION>/config.json` con schema versionado (course, defaults, evaluations, access); `defaults.json` en engine queda como fallback global.
  - ✅ Ventajas: Una fuente de verdad por sección, metadata completa (formas, pesos, fechas, tipos), extensible.
  - ❌ Desventajas: Rompe compatibilidad si scripts esperan solo `defaults.json`; requiere migrar `prepare_evaluation.py`, `export-publication-data.py`, `sync-section-indexes.py`.
- **Opción B**: Mantener `defaults.json` global + `evaluations.json` consolidado; no añadir `config.json` por sección.
  - ✅ Ventajas: Cambio mínimo.
  - ❌ Desventajas: Información dispersa, no hay metadata de formas/fechas/pesos por EV en un solo archivo.

**Pregunta concreta**: ¿Adoptamos `config.json` por sección (schema versionado) como fuente primaria, migrando los scripts que lean `defaults.json` y `evaluations.json`, o mantenemos la estructura actual?

---

## 6. Orden sugerido de prioridad

### P0: Seguridad, integridad, pérdida de información
1. **Limpiar `.claude/settings.local.json`** del repo referencia (no migrar, documentar exclusión).
2. **Excluir `evidencia_drive/`, `support/original-submissions/` con datos reales** de cualquier migración; documentar en AGENTS.md que `support/` puede contener PII y no se versiona.
3. **Validar que `grades.json` y `evaluations.json` sean generados, no fuentes** en el estándar (evitar duplicación y desincronización).

### P1: Alto impacto en productividad
4. **Export Relacional 3FN** (`export-relational-3fn.py` + `validate-relational-3fn-export.py` + schemas JSON) → `engine/scripts/`, `engine/schemas/relational-3fn/`, `scripts/export-relational-3fn.sh`, `scripts/validate-relational-3fn.sh`.
5. **Email Automation** → `engine/automation/email/` (lib/, templates/, tests/, package.json, send-student-emails.mjs) + wrapper `scripts/send-student-emails.sh` + `scripts/build-student-email-recipients.sh`.
6. **Student Results Web (SPA)** → `engine/scripts/build-student-results-web.mjs` + wrapper `scripts/build-student-results-web.sh` + output `exports/student-results-web/` (opcional, requiere Node).
7. **config.json por sección** → `init-course.sh` lo crea, scripts lo leen (`prepare_evaluation`, `export-publication`, `sync-indexes`).
8. **grades.json generado en export** → añadir paso en `export-publication-data.py` o `export-relational-3fn.py` que consolide `results/` → `grades.json`.

### P2: Mantenibilidad, testing, trazabilidad
9. **evaluations.json consolidado** → generar en `sync-section-indexes.py` desde `config.json`.
10. **Schemas JSON (relacional-3FN, student-portal)** → `engine/schemas/relational-3fn/`.
11. **Externalizar grade rules** → `engine/config/grade-rules.json` + cargar en scripts de export.
12. **Localización niveles desempeño** → mapa EN→ES en `defaults.json` o `grade-rules.json`, usar en export 3FN y web.
13. **Mejorar plan-template.md** → añadir secciones: Review strategy, Parallel review, Action log, Follow-up (basado en `FPY1101-010V/EV1/plan.md`).
14. **Actualizar AGENTS.md** → mencionar `exports/relational-3fn`, `exports/student-results-web`, web-dashboard legacy, `config.json` por sección.
15. **Crear CLAUDE.md base** → con convenciones del workspace (basado en `FPY1101-010V/CLAUDE.md`).
16. **Documentar patrón `support/` y `raw/`** en AGENTS.md como convenciones opcionales.

### P3: Conveniencia, mejoras menores
17. **Wrappers shell para scripts Node/Python** → `scripts/build-student-email-recipients.sh`, `scripts/build-student-results-web.sh`, `scripts/export-relational-3fn.sh`, `scripts/validate-relational-3fn.sh`.
18. **AVA import automation** → documentar como patrón en `docs/ideas/ava-integration.md` (no incluir código).
19. **README.md actualizado** → reflejar nueva estructura `exports/`, `automation/`, `schemas/`.

---

## 7. Próximos pasos

El análisis no presenta decisiones bloqueantes **excepto D1-D4 arriba**. Por favor indica cuál de estas acciones autorizas:

- **A.** Crear el plan de migración completo (detallado, con tareas, orden, responsables estimados).
- **B.** Profundizar un hallazgo específico (ej. revisar en detalle `export-relational-3fn.py` vs `export-publication-data.py`).
- **C.** Implementar únicamente las mejoras **P0** (limpieza, seguridad, integridad).
- **D.** Implementar una capacidad seleccionada (indica ID de la matriz, ej. C01, C04, C05).
- **E.** Descartar o reclasificar hallazgos (indica IDs a mover entre categorías).

**Responde con la letra de la opción y, si es D, el/los ID(s) de capacidad.**