# Validación del análisis FPY1101-010V vs academic-grading-with-ai

**Estado:** línea base vigente para arquitectura y planificación  
**Fecha:** 2026-08-01  
**Documento reemplazado como fuente de decisión:** `ANALYSIS_FPY1101_vs_BASE.md`

> El análisis original se conserva como registro histórico, pero no debe usarse para
> planificar ni implementar. Confundió bytes con líneas y declaró ausentes capacidades
> que el repositorio base ya contenía.

## 1. Hallazgo metodológico

Se verificó cada afirmación contra ambos repositorios. El informe original presentó dos
clases de error que alteraban sus conclusiones:

1. cifras de tamaño expresadas incorrectamente como líneas;
2. gaps falsos por inspección incompleta del repositorio base.

## 2. Capacidades que el base ya posee

No son trabajo de migración:

- `config.json` por sección: `init-course.sh` ya lo genera;
- `grades.json`: `sync-section-indexes.py` ya lo genera desde el export;
- `evaluations.json`: el generador ya existe;
- template de plan con review strategy, parallel review, action log y follow-up;
- importador AVA: el código base es equivalente al repositorio de referencia;
- wrappers/stubs de email: no existen en el base, por lo que no hay stub que reemplazar.

El gap de configuración se limita a evolución de schema y separación de autoridad entre
metadata estructural y grade policy.

## 3. Gaps genuinos

### G1 — Proyección relacional/auditoría

- Export relacional existente solo en referencia.
- 25 tablas, no 33.
- Incluye trazabilidad fuente → resultado → ajuste → nota.
- El validador realiza consistencia y desgloses; no es integridad referencial clásica.

Decisión arquitectónica vigente: no copiar la estructura como contrato central. El export
relacional será una proyección docente opcional y se validará por equivalencia semántica.

### G2 — Portal web

- Builder Node de aproximadamente 2014 líneas.
- Consume una vista de estudiante.
- Presenta EV/NP/ET, bonos, rúbrica y agregados.

Decisión arquitectónica vigente: la proyección estudiante no depende de 3FN. El portal
requiere hosting autenticado o contenido cifrado; PBKDF2 sobre códigos cortos no se acepta
como control suficiente.

### G3 — Automatización de email

- Node + Nodemailer.
- Dry-run, placeholders, logs CSV y tests confirmados.

Decisión arquitectónica vigente: adoptar el valor funcional, pero implementar
prepare/approve/execute, aprobación por hash y ledger durable.

### G4 — Schemas y grade policy

- Schemas relacionales presentes en referencia.
- Reglas PCT/EvG hardcodeadas.
- Localización EN→ES confirmada.

Decisión arquitectónica vigente: contratos versionados y grade policy tipada con
operadores registrados, sin expresiones libres.

### G5 — Convenciones

- `support/`, `raw/` y `CLAUDE.md` existen en referencia y no en base.

Decisión arquitectónica vigente: documentar como convenciones opcionales; datos reales y
PII permanecen fuera de Git.

## 4. Hallazgos descartados o corregidos

| Hallazgo original | Validación |
|---|---|
| SPA de 73K líneas | Falso; aproximadamente 2014 líneas |
| AVA import de 32K líneas | Confusión de tamaño con líneas |
| `assign_forms.py` de 6975 líneas | Confusión de bytes con líneas |
| `sync-section-indexes.py` de 5299 líneas | Confusión de bytes con líneas |
| 33 tablas 3FN | Falso; 25 tablas |
| Base sin `config.json` | Falso |
| Base sin `grades.json` | Falso |
| Base sin `evaluations.json` | Falso |
| Template base más simple | Falso |
| AVA solo documentado | Falso |
| Email con stubs en base | Falso; no existe implementación |

## 5. Prioridades válidas

Las capacidades operacionales ausentes son:

1. Publication Snapshot, schemas y gates como fundación corregida.
2. Grade Policy tipada.
3. Email controlado.
4. Portal seguro.
5. Proyecciones docente/BI, con 3FN solo si existe consumidor.
6. Convenciones y discovery posterior.

El roadmap vigente está en `docs/architecture/04-roadmap.md`.

## 6. Regla de uso

Para toda decisión futura:

- usar este documento para determinar gaps;
- usar `docs/architecture/` para decisiones objetivo;
- tratar `ANALYSIS_FPY1101_vs_BASE.md` únicamente como registro histórico;
- verificar contra código cualquier afirmación nueva antes de incorporarla al backlog.
