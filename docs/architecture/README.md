# Arquitectura — academic-grading-with-ai

Diseño objetivo para convertir el workspace en una plataforma académica de calificación
reproducible, auditable y segura, sin acoplarla a una asignatura, institución o proveedor
específico.

La arquitectura incorpora únicamente los gaps genuinos detectados al comparar el
workspace base con `FPY1101-010V`, pero corrige las decisiones que no eran suficientemente
seguras o generales antes de iniciar la implementación. La línea base verificada está en
[`VALIDATED_ANALYSIS_FPY1101_vs_BASE.md`](../../VALIDATED_ANALYSIS_FPY1101_vs_BASE.md).
El archivo `ANALYSIS_FPY1101_vs_BASE.md` se conserva solo como registro histórico.

## Estado

| Documento | Estado |
|---|---|
| [01-target-architecture.md](01-target-architecture.md) | Revisado y aprobado para planificación |
| [02-data-flow.md](02-data-flow.md) | Revisado y aprobado para planificación |
| [03-canonical-vs-derived.md](03-canonical-vs-derived.md) | Revisado y aprobado para planificación |
| [04-roadmap.md](04-roadmap.md) | Revisado; reemplaza C1–C6 por C0–C7 |
| [05-security-and-data-boundaries.md](05-security-and-data-boundaries.md) | Nuevo; obligatorio antes de implementar |
| [06-supported-profile-and-extension-points.md](06-supported-profile-and-extension-points.md) | Nuevo; delimita generalidad V1 |
| [07-grade-policy-contract.md](07-grade-policy-contract.md) | Nuevo; contrato tipado de reglas |
| [08-migration-strategy.md](08-migration-strategy.md) | Nuevo; evolución compatible desde el workspace actual |
| [09-verification-strategy.md](09-verification-strategy.md) | Nuevo; estrategia de pruebas y gates |
| [ADRs](ADRs/) | ADR-0001 a ADR-0011 aprobados (2026-08-01); C0 autorizado para implementación |

## Línea base validada

Se consideran descartadas las siguientes premisas del análisis original:

- Las cifras que confundían bytes con líneas.
- La supuesta ausencia de `config.json`, `grades.json` y `evaluations.json` en el base.
- La supuesta ausencia de secciones operativas en el template de plan.
- La supuesta ausencia del importador AVA.
- La existencia de stubs de email en el base.

Los gaps genuinos son:

1. Proyecciones relacionales/auditoría y su validación.
2. Automatización de email con preparación, aprobación y ejecución controlada.
3. Portal web de resultados.
4. Schemas y reglas de calificación versionadas.
5. Convenciones opcionales `support/`, `raw/` y `CLAUDE.md`.

## Principio rector

El núcleo no es `results.json` ni el export relacional. El núcleo es un
**Publication Snapshot** académico:

- versionado;
- inmutable;
- validado sintáctica y semánticamente;
- trazable a sus entradas;
- aprobado antes de publicarse;
- aislado por sección y publicación;
- capaz de generar proyecciones distintas para estudiante, docente y BI.

`results.json` conserva el rol de contrato canónico de resultados dentro del snapshot,
pero no es suficiente por sí solo para reproducir una publicación.

## Restricciones no negociables

- PII y secretos no se versionan en Git.
- El RUT o el nombre nunca son la identidad técnica primaria.
- Los builders puros son deterministas; email, publicación y rotación de secretos son
  ejecutores con efectos, auditables e idempotentes.
- El portal estático no confía en ocultamiento visual ni en códigos cortos: usa hosting
  autenticado o contenido cifrado con capacidad de alta entropía.
- `grade-policy.json` usa operadores cerrados y tipados; no contiene expresiones libres.
- Discovery puede proponer instancias de configuración, nunca redefinir schemas o el
  metamodelo del core.

## Navegación recomendada

1. Leer [01-target-architecture.md](01-target-architecture.md).
2. Revisar [05-security-and-data-boundaries.md](05-security-and-data-boundaries.md).
3. Revisar [06-supported-profile-and-extension-points.md](06-supported-profile-and-extension-points.md).
4. Revisar [07-grade-policy-contract.md](07-grade-policy-contract.md).
5. Revisar [08-migration-strategy.md](08-migration-strategy.md) y
   [09-verification-strategy.md](09-verification-strategy.md).
6. ADR-0001 a ADR-0011 aprobados (2026-08-01).
7. Ejecutar el roadmap C0–C7 de [04-roadmap.md](04-roadmap.md).

## Estado de implementación

- **C0** — Autorizado. Implementación en `feat/c0-security-data-boundaries`:
  límites de almacenamiento, clasificación, identidad opaca, migración segura,
  scanner de PII/secretos, fixtures sintéticos, workspace status y runbooks.
  Detalle en [docs/implementation/C0-IMPLEMENTATION-PLAN.md](../implementation/C0-IMPLEMENTATION-PLAN.md).
- **C1–C7** — Pendientes. No deben implementarse como parte de C0.
