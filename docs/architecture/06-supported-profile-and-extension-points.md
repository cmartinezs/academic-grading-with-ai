# 06 — Perfil soportado V1 y puntos de extensión

## 1. Propósito

Evitar una promesa de generalidad ilimitada. La arquitectura V1 soporta un dominio
académico explícito y ofrece extension points controlados para ampliar casos sin
introducir condicionales por curso o institución en el core.

## 2. Perfil soportado V1

### Entidades

- institución opcional;
- curso/asignatura;
- sección;
- periodo;
- estudiante con identidad opaca;
- evaluación;
- forma/variante opcional;
- intento único por defecto;
- rúbrica/componentes;
- resultado revisado;
- policy de calificación;
- publication snapshot.

### Tipos de evaluación

- individual;
- con forma/variante;
- cuantitativa;
- basada en porcentaje, puntos o escala configurable;
- sumativa o formativa;
- obligatoria, opcional o bonus;
- con componentes ponderados.

### Reglas soportadas

- weighted average;
- sum;
- percentage-to-grade scale;
- missing policy;
- additive bonus;
- cap/floor;
- replacement;
- conditional inclusion basada en estados tipados;
- rounding en stages explícitos.

### Publicación

- vista individual de estudiante;
- vista detallada de docente;
- vista BI agregada;
- notificación por email.

## 3. Fuera de alcance V1

No se implementan como comportamiento genérico hasta diseñar contratos específicos:

- entregas grupales con nota común y componentes individuales;
- coevaluación o evaluación entre pares;
- múltiples intentos con selección de mejor/último intento;
- evaluaciones puramente cualitativas sin mapeo a escala;
- outcomes de aprobación/reprobación sin score;
- reglas basadas en asistencia u otras fuentes externas;
- curvas estadísticas institucionales;
- apelaciones con workflow formal;
- sincronización bidireccional LMS;
- autorización institucional centralizada;
- actualización de notas ya publicadas in-place.

Estos casos no deben resolverse mediante campos ad hoc o scripts de una sección.

## 4. Puntos de extensión

### Identity Adapter

Convierte identificadores institucionales a `studentId` opacos y mantiene mappings
privados.

Contrato:

```text
external identity input → validated private subject record
```

### Evidence Parser

Convierte una forma de evidencia revisada a un resultado normalizado. Los parsers son
versionados, probados con fixtures y no ejecutan reglas de calificación.

```text
reviewed evidence → normalized assessment result
```

### Assessment Type

Define semántica estructural de una evaluación sin calcular automáticamente notas.

Ejemplos futuros:

- individual;
- group-with-individual-defense;
- pass-fail;
- portfolio.

### Grade Operator

Operador registrado, tipado y determinista. Debe declarar:

- input schema;
- output schema;
- precondiciones;
- invariantes;
- orden/fase;
- manejo de nulos;
- suite de conformidad.

### Scale Adapter

Transforma scores normalizados a una escala académica explícita.

Ejemplos:

- 1.0–7.0;
- 0–100;
- A–F;
- pass/fail.

### Publisher

Consume un Publication Snapshot aprobado y genera una proyección o ejecuta una acción.
Nunca parsea evidencia ni recalcula reglas.

### Institutional Adapter

Integra LMS, AVA u otros sistemas. Se mantiene fuera del core y traduce contratos
institucionales a contratos internos.

## 5. Reglas de extensión

Una extensión nueva requiere:

1. Caso de uso y consumidor reales.
2. Contrato versionado.
3. Fixtures sintéticos.
4. Validación sintáctica y semántica.
5. Threat model si procesa PII o publica datos.
6. Compatibilidad documentada.
7. Ausencia de nombres de curso/institución en el core.
8. ADR cuando cambie una frontera arquitectónica.

## 6. Anti-patrones prohibidos

```python
if course == "FPY1101":
    ...
```

```python
if institution == "DUOC":
    ...
```

```json
{"when": "level>=4 and teacher prefers replacement"}
```

```text
RUT usado como primary key pública
```

```text
Publisher que vuelve a parsear Markdown o recalcula la nota
```

## 7. Criterio de generalidad

La arquitectura se considera genérica cuando una nueva sección dentro del perfil V1 se
configura mediante datos validados y operadores existentes, sin modificar el core.

No se considera un defecto que un caso fuera del perfil requiera diseño adicional. Es
preferible rechazar explícitamente un caso no soportado que aceptarlo con semántica
ambigua.

## 8. Evolución

La expansión del perfil sigue este proceso:

```text
real use case
→ domain analysis
→ contract proposal
→ ADR
→ operator/adapter implementation
→ conformance fixtures
→ compatibility release
```

Discovery asistido por LLM puede ayudar a mapear material de un docente al perfil
existente, pero no puede crear nuevos extension points por sí solo.
