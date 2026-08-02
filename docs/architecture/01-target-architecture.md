# 01 — Arquitectura objetivo

Estado: diseño revisado. No autoriza implementación hasta aprobar los ADRs y completar C0.

## 1. Objetivo

Construir un workspace académico que transforme resultados revisados en una publicación
versionada, auditable y segura, y que luego genere proyecciones específicas para:

- estudiantes;
- docentes;
- directiva/BI;
- automatizaciones operacionales como email.

La arquitectura debe reutilizar lo aprendido en `FPY1101-010V` sin copiar sus decisiones
accidentales ni convertir reglas institucionales particulares en comportamiento del core.

## 2. Unidad arquitectónica central: Publication Snapshot

El artefacto central es un **Publication Snapshot** inmutable. Representa exactamente
qué información académica fue aprobada para una sección en una publicación concreta.

```text
private working sources
├── section-config.json
├── roster privado
├── resultados revisados
├── grade-policy.json
└── evidencia/provenance
          │
          ▼
validate → normalize → calculate → assemble → approve
          │
          ▼
Publication Snapshot <sectionId, publicationId>
├── manifest.json
├── canonical/results.json
├── canonical/evaluations.json
├── canonical/policy.json
├── canonical/subjects.json
├── provenance/source-hashes.json
└── approval.json
          │
          ├──▶ student projection
          ├──▶ teacher-audit projection
          ├──▶ BI aggregate projection
          └──▶ email preparation
```

`results.json` es el contrato canónico de resultados dentro del snapshot. No es la única
fuente necesaria para reproducir una publicación.

## 3. Identidad del snapshot

Cada snapshot declara como mínimo:

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "sec_01J...",
  "publicationId": "pub_01J...",
  "supersedesPublicationId": null,
  "status": "approved",
  "engineVersion": "...",
  "policyVersion": "...",
  "sourceHashes": {},
  "createdAt": "...",
  "approvedAt": "...",
  "approvedBy": "..."
}
```

`publicationId` es el eje común para portal, email, BI, auditoría, correcciones y
revocaciones.

## 4. Capas y responsabilidades

```text
┌────────────────────────────────────────────────────────────────────┐
│ discovery/ — opcional y no determinista                            │
│ Propone instancias de config/reglas compatibles con schemas        │
│ existentes. Nunca crea schemas ni código del core.                 │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ aprobación humana
┌──────────────────────────────▼─────────────────────────────────────┐
│ private workspace data                                             │
│ roster, submissions, resultados revisados, config, policy          │
│ Fuera de Git; acceso local controlado.                              │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
┌──────────────────────────────▼─────────────────────────────────────┐
│ core/ — Python, determinista, sin efectos externos                 │
│ adapters     normalizan entradas institucionales                    │
│ parsers      convierten evidencia revisada a contratos tipados      │
│ policy       calcula notas con operadores registrados               │
│ snapshot     ensambla bundles inmutables                            │
│ validators   schemas + invariantes semánticos                       │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ snapshot aprobado
          ┌────────────────────┼──────────────────────┐
          ▼                    ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌───────────────────────┐
│ pure projections │  │ effectful portal │  │ effectful email       │
│ teacher / BI     │  │ publish/revoke   │  │ prepare/approve/      │
│ deterministic    │  │ encrypted/auth   │  │   execute             │
│                  │  │                  │  │ ledger/idempotency    │
│                  │  │                  │  │ templates versioned   │
└──────────────────┘  └──────────────────┘  └───────────────────────┘
```

### 4.1 Builders puros

Deben cumplir `mismo input lógico + misma versión → mismo output lógico`:

- parsing y normalización;
- cálculo de reglas;
- ensamblaje del snapshot;
- proyección estudiante;
- proyección docente;
- proyección BI;
- previews de email;
- HTML base antes de incorporar secretos o metadata operacional.

### 4.2 Ejecutores con efectos

No se consideran deterministas. Deben ser idempotentes, auditables y reanudables:

- generación/rotación de claves;
- publicación a hosting;
- revoke/purge;
- envío SMTP;
- logging operacional;
- reintentos;
- actualización de ledger;
- email delivery (prepare → approve → execute).

## 5. Límite de datos

Se distinguen cuatro zonas:

```text
source-controlled code
runtime private data
runtime operational state
publishable artifacts
```

### Source-controlled code

Código, schemas, fixtures sintéticos, documentación y ejemplos sanitizados.

### Runtime private data

Roster, RUT, emails, entregas, feedback privado y snapshots completos. Nunca se versiona.

### Runtime operational state

Ledgers de envío, locks, receipts, claves y metadata de publicación. Persistente y
respaldable, pero fuera de Git y fuera de artefactos regenerables.

### Publishable artifacts

Solo proyecciones mínimas, validadas para una audiencia concreta.

## 6. Identidad de estudiantes

El core usa un identificador opaco estable:

```json
{
  "studentId": "stu_01J...",
  "externalIdentifiers": {
    "rut": "...",
    "avaUser": "..."
  }
}
```

- `studentId` es la única clave transversal en contratos internos.
- RUT, email y otros identificadores externos permanecen en el store privado.
- Un hash simple de RUT no es una anonimización aceptable.
- Los publishers reciben únicamente los campos necesarios para su audiencia.

## 7. Configuración y autoridad

### `section-config.json`

Responsable de metadata estructural:

- curso y sección;
- periodo;
- evaluaciones;
- formas;
- fechas;
- tipos;
- referencias a policy;
- configuración de publicación no secreta.

### `grade-policy.json`

Única autoridad para:

- escala;
- ponderaciones;
- tratamiento de faltantes;
- ajustes;
- bonos;
- reemplazos;
- topes;
- redondeo.

Los pesos no se duplican entre `section-config.json`, defaults y policy. La config puede
referenciar componentes; la policy decide cómo se calculan.

### Defaults

Solo valores de inicialización. No participan silenciosamente en una publicación una
vez que existe una policy explícita.

## 8. Proyecciones por audiencia

### 8.1 Estudiante

Documento individual con sus resultados, componentes y feedback permitido. No depende
del export 3FN.

### 8.2 Docente/auditoría

Proyección detallada y trazable. Puede materializarse como tablas relacionales 3FN si
existe un consumidor concreto. No se publica en el mismo directorio que el portal.

### 8.3 Directiva/BI

Agregados sin PII, gobernados por una política anti-inferencia. No se deriva mediante una
simple selección de columnas desde tablas privadas: tiene contrato y validación propios.

## 9. Portal

Se soportan dos modos:

1. **Hosting autenticado**: preferido cuando exista infraestructura con autorización real.
2. **Hosting estático cifrado**: un blob AES-GCM por estudiante, objeto no enumerable y
   capacidad de alta entropía entregada en el fragmento de URL. El fragmento no llega al
   servidor.

No se considera seguro:

- ocultar datos con JavaScript;
- publicar JSON en texto plano y pedir un código;
- usar PINs cortos protegidos solo por PBKDF2;
- asumir que TLS equivale a autorización.

## 10. Email

El flujo es de dos fases:

```text
prepare → previewHash → human approval → execute → durable ledger
```

La aprobación queda ligada al hash exacto de destinatarios, plantilla y payload. Si el
contenido cambia, la aprobación queda invalidada.

## 11. Lifecycle académico

Estados mínimos:

```text
draft → reviewed → approved → published
                         ├──▶ superseded
                         ├──▶ corrected
                         └──▶ revoked
```

Un email no tiene rollback. Una publicación retirada puede persistir en caché o haber
sido descargada. La arquitectura define acciones compensatorias, no reversión ficticia.

## 12. Alcance genérico V1

La versión inicial soporta:

- evaluaciones individuales o por forma;
- rúbricas cuantitativas;
- escalas configurables;
- ponderaciones;
- faltantes;
- bonos, topes, ajustes y reemplazos mediante operadores registrados;
- una o más evaluaciones por sección;
- proyecciones por audiencia.

No se promete soporte universal. Trabajo grupal con componentes individuales, múltiples
intentos, evaluaciones puramente cualitativas y reglas institucionales excepcionales se
incorporan mediante extension points explícitos y contratos versionados.

## 13. Decisiones D1–D12 revisadas

| ID | Decisión revisada |
|---|---|
| D1 | `results.json` es contrato canónico de resultados; el Publication Snapshot es la unidad reproducible. |
| D2 | `section-config` contiene estructura; `grade-policy` es autoridad exclusiva de cálculo. |
| D3 | 3FN es una proyección docente opcional, no dependencia de portal ni BI. |
| D4 | Reglas con operadores cerrados, tipados y versionados; no DSL textual libre. |
| D5 | Node.js opcional solo detrás de contratos de publishers. |
| D6 | Schemas SemVer, validación sintáctica y semántica; determinismo solo para builders puros. |
| D7 | PII fuera de Git, identidad opaca, data minimization por audiencia. |
| D8 | Email prepare/approve/execute con hash y ledger durable. |
| D9 | Portal autenticado o cifrado con capability de alta entropía. |
| D10 | `support/` y `raw/` son convenciones opcionales con clasificación de datos. |
| D11 | AVA queda congelado; se trata como adapter institucional existente. |
| D12 | Discovery solo propone instancias compatibles con schemas existentes. |

## 14. Condición de inicio de implementación

No se inicia C1 hasta que estén aprobados:

- ADR-0001 a ADR-0011;
- threat model y límites de datos;
- perfil soportado V1;
- contrato de reglas;
- estructura de almacenamiento por sección/publicación;
- fixtures completamente sintéticos.
