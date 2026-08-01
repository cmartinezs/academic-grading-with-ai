# 02 — Flujo de datos y ejecución

## 1. Flujo principal

```text
PRIVATE WORKSPACE DATA

[roster privado]      [section-config]      [grade-policy]
       │                     │                    │
       └──────────────┬──────┴──────────────┬─────┘
                      │                     │
[results/*.md revisados]                     │
                      │                     │
                      ▼                     │
             parse + normalize              │
                      │                     │
                      ▼                     ▼
             canonical results ───────▶ policy engine
                                              │
                                              ▼
                                     calculated results
                                              │
                  source hashes + versions ───┤
                                              ▼
                                  Publication Snapshot
                               <sectionId, publicationId>
                                              │
                         review + explicit approval
                                              │
             ┌────────────────────────────────┼────────────────────────────┐
             ▼                                ▼                            ▼
   student projection              teacher-audit projection      BI projection
             │                                │                            │
             ▼                                ▼                            ▼
 encrypted/auth portal          optional relational export      aggregate release
             │
             └──────────────▶ email preparation
                                      │
                               preview + previewHash
                                      │
                               human approval
                                      │
                                      ▼
                               SMTP execution
                                      │
                               durable ledger
```

## 2. Separación entre build y ejecución

### Build determinista

```text
normalize
→ validate input
→ calculate
→ validate invariants
→ assemble snapshot in temp directory
→ generate projections
→ validate outputs
→ atomically promote snapshot
```

El build no envía emails, no publica en red y no genera secretos.

### Ejecución con efectos

```text
approved snapshot
→ prepare operation
→ materialize exact plan
→ calculate operation hash
→ human approval of hash
→ acquire lock
→ execute
→ persist receipt/ledger atomically
→ release lock
```

La ejecución puede producir timestamps, IDs de proveedores y resultados variables. Su
propiedad objetivo es idempotencia operacional, no igualdad byte a byte.

## 3. Estructura de almacenamiento objetivo

```text
runtime/
├── private/
│   └── sections/<sectionId>/
│       ├── roster.json
│       ├── evidence/
│       ├── reviewed-results/
│       └── policies/
├── publications/
│   └── sections/<sectionId>/
│       └── <publicationId>/
│           ├── manifest.json
│           ├── canonical/
│           ├── provenance/
│           ├── approvals/
│           └── projections/
│               ├── student/
│               ├── teacher/
│               └── bi/
└── state/
    ├── email-ledger/
    ├── portal-receipts/
    ├── locks/
    └── secrets/
```

Los nombres definitivos pueden adaptarse a la implementación, pero las tres categorías
`private`, `publications` y `state` no deben mezclarse.

## 4. Atomicidad del snapshot

El generador construye en un directorio temporal:

```text
.tmp/<publicationId>/
```

Solo después de pasar todos los gates realiza una promoción atómica a:

```text
publications/sections/<sectionId>/<publicationId>/
```

Nunca se actualiza un snapshot aprobado in-place. Una corrección crea otro
`publicationId` y declara `supersedesPublicationId`.

## 5. Gates

| Gate | Valida | Resultado ante fallo |
|---|---|---|
| G0 Data boundary | rutas, permisos, PII fuera de Git | abortar |
| G1 Section config | schema + referencias existentes | abortar |
| G2 Roster | identidad opaca, unicidad, campos privados | abortar |
| G3 Results | schema + estudiante/evaluación existentes | abortar |
| G4 Policy | operadores conocidos, tipos y referencias | abortar |
| G5 Calculation | pesos, escalas, redondeo, invariantes | abortar |
| G6 Snapshot | hashes, versiones, completitud, lifecycle | abortar |
| G7 Projection | contrato específico de audiencia | abortar |
| G8 Privacy | PII permitida, cohortes BI, no dataset global | abortar |
| G9 Operation | snapshot aprobado + plan/hash autorizado | abortar |

## 6. Flujo de portal

### Modo autenticado

```text
student projection
→ deploy privado
→ hosting aplica identidad/autorización
→ receipt de publicación
```

### Modo estático cifrado

```text
student projection
→ generate random content key
→ encrypt AES-GCM
→ publish encrypted blob under random object id
→ deliver capability URL with key in fragment
→ persist publication receipt without plaintext key
```

El servidor recibe el object ID, pero no la llave del fragmento. La seguridad depende de
la entropía de la capability y del cifrado, no de ocultar controles en la interfaz.

## 7. Flujo de email

```text
snapshot aprobado
→ join mínimo con roster privado
→ render recipients + subjects + bodies
→ generate previews
→ calculate previewHash
→ teacher approves previewHash
→ execute with idempotency key
→ persist per-recipient result
```

Clave idempotente mínima:

```text
sectionId + publicationId + studentId + recipient + templateVersion + intent
```

Si cambia cualquiera de estos valores, se requiere una nueva preparación y aprobación.

## 8. Flujo BI

```text
approved snapshot
→ aggregate using allow-listed dimensions
→ enforce minimum cohort
→ complementary suppression
→ disclosure-risk validation
→ immutable BI release
```

BI no consume directamente tablas privadas publicables ni comparte directorio con el
portal.

## 9. Flujo discovery

```text
raw material
→ LLM proposal
→ schema validation
→ deterministic diff against current config
→ human review
→ explicit acceptance
→ versioned config/policy instance
```

Discovery no modifica snapshots aprobados, no ejecuta publishers y no crea nuevos schemas.
