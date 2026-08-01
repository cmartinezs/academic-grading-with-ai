# 03 — Autoridad de datos, snapshots y artefactos derivados

## 1. Categorías de información

La arquitectura distingue cuatro categorías. Ninguna debe confundirse con otra.

| Categoría | Ejemplos | Mutable | Versionada en Git |
|---|---|---:|---:|
| Configuración controlada | schemas, operadores, templates, fixtures sintéticos | Sí | Sí |
| Datos privados de trabajo | roster, RUT, email, entregas, resultados revisados | Sí | No |
| Publication Snapshot | resultados calculados, policy snapshot, hashes, aprobación | No | No |
| Estado operacional | ledger email, locks, receipts, claves, intentos | Sí | No |

## 2. Fuentes autoritativas de trabajo

| Fuente | Rol | Autoridad |
|---|---|---|
| `section-config.json` | estructura académica y metadata | estructura de sección |
| roster privado | identidad y contacto | identidad externa/operacional |
| resultados revisados | evidencia aprobada por el docente | observación académica |
| `grade-policy.json` | cálculo y ajustes | política de calificación |
| schemas/engine version | interpretación de contratos | semántica técnica |

Estas fuentes se combinan para producir un snapshot. Ninguna por sí sola reproduce una
publicación completa.

## 3. Contrato canónico de resultados

Dentro del snapshot, `canonical/results.json` es la representación canónica de los
resultados individuales. Debe contener únicamente identificadores opacos y referencias
estables.

No debe contener como clave primaria:

- RUT;
- email;
- nombre normalizado;
- ruta de archivo como identidad;
- índice de posición en roster.

Un resultado mínimo referencia:

```json
{
  "studentId": "stu_01J...",
  "assessmentId": "asm_01J...",
  "attemptId": "att_01J...",
  "status": "graded",
  "components": [],
  "calculated": {},
  "evidenceRefs": []
}
```

## 4. Publication Snapshot

El snapshot contiene todos los elementos necesarios para reconstruir y auditar una
publicación sin consultar defaults mutables ni archivos externos no identificados.

```text
<publicationId>/
├── manifest.json
├── canonical/
│   ├── section.json
│   ├── subjects.json
│   ├── assessments.json
│   ├── results.json
│   └── policy.json
├── provenance/
│   ├── source-hashes.json
│   ├── engine.json
│   └── migrations.json
├── approvals/
│   └── publication-approval.json
└── projections/
    ├── student/
    ├── teacher/
    └── bi/
```

### Invariantes

- El directorio es inmutable después de `approved`.
- Todos los archivos declarados aparecen en el manifest.
- Todos los hashes son verificables.
- La policy aplicada está incluida como snapshot, no solo referenciada por ruta.
- Las versiones de schema y engine están registradas.
- Una corrección crea una nueva publicación.

## 5. Artefactos derivados

| Artefacto | Fuente | Consumidor | ¿Determinista? |
|---|---|---|---:|
| `grades.json` de compatibilidad | snapshot aprobado | herramientas existentes | Sí |
| `evaluations.json` de compatibilidad | section snapshot | discovery/navegación | Sí |
| proyección estudiante | snapshot aprobado | portal/email | Sí |
| proyección docente | snapshot aprobado | consulta/auditoría | Sí |
| export relacional | proyección docente | análisis/BI interno | Sí |
| proyección BI | snapshot aprobado | directiva | Sí |
| previews de email | snapshot + roster + template | docente | Sí, salvo metadata separada |
| blob cifrado | proyección estudiante + clave aleatoria | portal | No byte a byte |
| envío SMTP | plan aprobado | estudiante | No; debe ser idempotente |

## 6. Compatibilidad con artefactos existentes

`evaluations/<SECTION>/grades.json` y `evaluations.json` pueden mantenerse como vistas de
compatibilidad mientras existan consumidores actuales. No son fuentes canónicas ni deben
editarse manualmente.

Cada vista de compatibilidad debe declarar:

- `sourcePublicationId`;
- `schemaVersion`;
- `generatedBy`;
- hash del contenido canónico origen.

## 7. Namespacing

Toda salida debe estar aislada por sección y publicación:

```text
publications/sections/<sectionId>/<publicationId>/
```

Queda prohibido mantener una única ruta global como
`exports/publication-input/course/` para múltiples secciones sin namespace. Esa ruta puede
existir temporalmente como alias de compatibilidad hacia una publicación explícita.

## 8. Reglas de autoridad

1. `section-config` define qué existe; no define cómo se calcula.
2. `grade-policy` define cómo se calcula; no contiene identidad ni secretos.
3. El roster define contacto e identidad externa; no define resultados.
4. Los resultados revisados definen evidencia; no calculan silenciosamente la nota final.
5. El snapshot captura las versiones exactas de todas las autoridades anteriores.
6. Los publishers nunca vuelven a parsear Markdown ni reinterpretan reglas.

## 9. Defaults

Los defaults sirven únicamente para inicializar una configuración nueva. Una publicación
no puede depender de un default mutable no capturado.

Antes de crear el snapshot, todos los defaults efectivos deben resolverse y materializarse
en `canonical/section.json` o `canonical/policy.json`.

## 10. Estado operacional no regenerable

No se ubica dentro de `exports/`:

- ledger de email;
- receipts de hosting;
- locks;
- secretos;
- claves de cifrado;
- resultados de entrega SMTP;
- historial de reintentos.

Aunque parte de esta información pueda reconstruirse desde proveedores externos, se trata
como estado operacional durable, no como artefacto derivado.
