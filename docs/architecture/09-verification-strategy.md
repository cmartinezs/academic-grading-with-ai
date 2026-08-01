# 09 — Estrategia de verificación y calidad

## 1. Objetivo

Demostrar que la arquitectura preserva semántica académica, evita exposición de datos y
opera correctamente ante fallos, concurrencia y evolución de contratos.

## 2. Pirámide de pruebas

### Unitarias

- parsers y normalizadores;
- operadores de grade policy;
- validators semánticos;
- hashing/manifest;
- render de templates;
- masking y data minimization.

### Contract tests

- schemas de config, policy, snapshot y proyecciones;
- CLI/file boundaries Python ↔ Node;
- compatibility views;
- provider adapters mockeados.

### Golden/conformance tests

- casos FPY1101 sanitizados;
- outputs académicos esperados;
- traces de cálculo;
- migración legacy → snapshot.

Los golden tests comparan semántica normalizada. Timestamps y metadata operacional no se
mezclan con el contenido lógico.

### Property tests

- notas dentro de la escala;
- caps/floors respetados;
- weighted averages estables;
- ausencia de ciclos en policy;
- invariancia ante orden de objetos cuando no es semántico;
- IDs opacos únicos;
- manifest completo.

### Integración

- build completo del snapshot;
- staging y promoción atómica;
- generación de proyecciones;
- prepare/approve/execute de email con transporte fake;
- portal cifrado y descifrado en navegador de prueba;
- disclosure validator BI.

### End-to-end

Curso completamente sintético:

```text
init
→ import roster
→ create evaluations
→ add reviewed results
→ calculate
→ create snapshot
→ approve
→ prepare email
→ publish encrypted portal
→ generate teacher/BI projections
→ correct publication
→ revoke old publication
```

## 3. Seguridad y privacidad

### Tests de repositorio

- secret scanning;
- PII patterns;
- prohibición de datos bajo rutas versionadas;
- fixtures marcados como synthetic.

### Portal

- payload no legible sin clave;
- object IDs no enumerables;
- ausencia de dataset global;
- XSS con nombres/feedback maliciosos;
- CSP;
- fragment no enviado en requests;
- rotación invalida nueva distribución;
- cache/purge behavior documentado.

### Email

- cambio de un byte invalida `previewHash`;
- lock evita ejecución concurrente;
- restart conserva ledger;
- timeout ambiguo no reenvía automáticamente;
- auth failure detiene batch;
- invalid recipient no detiene destinatarios válidos;
- logs no filtran PII.

### BI

- grupos bajo umbral suprimidos;
- supresión complementaria;
- diferencia entre releases no revela celdas;
- schema rechaza IDs y PII;
- dimensiones no allow-listed fallan.

## 4. Determinismo

Para builders puros:

- clock inyectable;
- orden estable;
- serialización normalizada;
- locale/timezone controlados;
- versiones de dependencias pinneadas;
- mismo fixture produce mismo hash lógico.

Para executors:

- tests de idempotencia;
- receipts;
- locks;
- retries;
- reconciliación;
- compensación.

## 5. Failure injection

Se prueban fallos en:

- lectura de evidencia;
- schema inválido;
- policy inválida;
- disco lleno durante staging;
- crash antes/después de promoción;
- crash antes/después de persistir ledger;
- SMTP timeout;
- hosting parcial;
- purge incompleto;
- corruption de manifest;
- pérdida temporal del state store.

La prueba debe identificar el estado final permitido y el procedimiento de recuperación.

## 6. Migraciones

Cada migración major incluye:

- fixture old-version;
- expected new-version;
- reporte de cambios;
- round-trip cuando aplique;
- idempotencia de migración;
- rechazo de downgrade inseguro;
- preservation de hashes/provenance relevantes.

## 7. Compatibilidad con FPY1101

La referencia se usa como corpus de conformidad sanitizado, no como estructura obligatoria.
Se validan:

- resultados por IE;
- ponderaciones;
- PCT/EvG;
- caps y redondeo;
- proyección estudiante;
- email dry-run;
- trazabilidad.

No se exige reproducir nombres de archivos, número de tablas o decisiones accidentales.

## 8. Gates CI

Orden mínimo:

```text
format/lint
→ unit
→ schemas
→ semantic validators
→ property tests
→ contract tests
→ security scans
→ integration synthetic
→ reproducibility
```

Tests que requieren SMTP/hosting real se ejecutan en ambientes controlados y nunca con
datos reales de estudiantes.

## 9. Evidencia de aceptación por corte

Cada corte entrega:

- requisitos satisfechos;
- tests y resultados;
- fixtures usados;
- ADRs implementados;
- riesgos residuales;
- rollback/compensation probado;
- lista de desviaciones.

## 10. Definition of Done arquitectónica

Una capacidad no está terminada solo porque genera un archivo. Debe:

- consumir el contrato correcto;
- validar entrada y salida;
- respetar data boundaries;
- emitir provenance;
- tener pruebas de fallo;
- documentar operación y recuperación;
- no introducir una segunda fuente de autoridad.
