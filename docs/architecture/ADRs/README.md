# Architecture Decision Records

## Estado

Los ADRs ADR-0001 a ADR-0011 fueron **aprobados** por el propietario del repositorio el
2026-08-01. Con ello, el corte **C0** (Threat model, PII, identidad y límites de
almacenamiento) queda **autorizado para implementación**. Los cortes C1–C7 permanecen
**pendientes** hasta completar las condiciones de inicio definidas en el roadmap.

| ADR | Decisión |
|---|---|
| [ADR-0001](ADR-0001.md) | Publication Snapshot como unidad reproducible |
| [ADR-0002](ADR-0002.md) | Configuración estructural separada de grade policy |
| [ADR-0003](ADR-0003.md) | Proyecciones separadas por audiencia; 3FN opcional |
| [ADR-0004](ADR-0004.md) | Grade Policy tipada con operadores registrados |
| [ADR-0005](ADR-0005.md) | Node.js opcional detrás de contratos de publishers |
| [ADR-0006](ADR-0006.md) | Versionamiento, validación y determinismo por capa |
| [ADR-0007](ADR-0007.md) | Identidad opaca, clasificación y PII fuera de Git |
| [ADR-0008](ADR-0008.md) | Portal autenticado o estático con contenido cifrado |
| [ADR-0009](ADR-0009.md) | Email en dos fases con ledger durable |
| [ADR-0010](ADR-0010.md) | Discovery propone instancias, no redefine el core |
| [ADR-0011](ADR-0011.md) | Lifecycle, provenance y correcciones de publicación |

## Reglas de gobernanza

- Un ADR aprobado no se edita para cambiar su decisión: se crea otro ADR que lo reemplaza.
- Toda implementación debe enlazar los ADRs que satisface.
- Una desviación requiere registrar contexto, riesgo y estrategia de compatibilidad.
- Los ADRs describen decisiones y consecuencias; los contratos detallados viven en los
  documentos de arquitectura correspondientes.
