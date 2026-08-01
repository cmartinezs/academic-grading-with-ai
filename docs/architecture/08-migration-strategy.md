# 08 — Estrategia de migración desde el workspace actual

## 1. Objetivo

Evolucionar desde las rutas y scripts actuales hacia Publication Snapshots sin romper el
flujo vigente ni reinterpretar silenciosamente resultados históricos.

## 2. Estado de origen

El workspace actual utiliza, entre otros:

```text
evaluations/<SECTION>/config.json
evaluations/<SECTION>/students.json
evaluations/<SECTION>/<EV>/form-*/results/*.md
evaluations/<SECTION>/grades.json
evaluations/<SECTION>/evaluations.json
exports/publication-input/course/*.json
```

`export-publication-data.py` parsea Markdown y genera archivos globales de publicación.
`sync-section-indexes.py` mantiene vistas de compatibilidad.

## 3. Principios

- No migrar datos reales mediante fixtures o commits.
- No cambiar el significado de una nota durante una migración estructural.
- Comparar semántica, no solo formato.
- Mantener comandos actuales mediante adapters temporales.
- No sobrescribir publicaciones históricas.
- Toda migración es explícita, versionada y reportada.

## 4. Etapas

### M0 — Inventario y respaldo

- Identificar secciones y rutas reales.
- Detectar PII versionada o exports mezclados.
- Generar backup fuera de Git.
- Congelar hashes de entradas y outputs actuales.
- Crear fixtures sintéticos equivalentes.

Salida: `migration-inventory.json` privado y baseline de conformidad sintético.

### M1 — Introducir raíces de runtime

- Configurar `runtime/private`, `runtime/publications` y `runtime/state`.
- Mantener lectura temporal de rutas legacy.
- Bloquear escritura de datos reales en Git.
- Crear mapping de identidad opaca.

La migración de identidad produce un reporte:

```text
external identifier → studentId opaco
```

El mapping permanece privado.

### M2 — Snapshot builder paralelo

- Mantener `export-publication-data.py` como entrada legacy.
- Añadir un adapter que convierta su output normalizado al primer Publication Snapshot.
- No activar publishers nuevos.
- Ejecutar old/new en paralelo sobre fixtures.

Criterio: equivalencia semántica de resultados, estados, componentes y notas.

### M3 — Migrar configuración y policy

- Convertir defaults y pesos actuales a `grade-policy.json` explícita.
- Validar contra casos de referencia.
- Registrar cualquier ambigüedad para decisión humana.
- Capturar policy efectiva en el snapshot.

No se infieren reglas desconocidas. Una regla sin equivalencia bloquea la migración.

### M4 — Vistas de compatibilidad

Generar desde el snapshot:

- `grades.json`;
- `evaluations.json`;
- alias opcional de `exports/publication-input/course/`.

Cada artefacto declara `sourcePublicationId`. Los consumidores actuales siguen funcionando
mientras se migran.

### M5 — Cambiar autoridad de publishers

- Portal, email y proyecciones leen snapshots aprobados.
- Se prohíbe que un publisher lea directamente Markdown o rutas legacy.
- Los aliases dejan de ser autoridad.

### M6 — Retirar rutas legacy

Solo después de:

- inventario de consumidores;
- telemetría/validación de uso;
- periodo de compatibilidad;
- plan de rollback probado;
- documentación actualizada.

## 5. Migración de una sección

```text
1. validate legacy workspace
2. create private runtime root
3. import roster and generate opaque IDs
4. normalize section config
5. materialize grade policy
6. parse reviewed results
7. compare legacy vs new calculations
8. resolve discrepancies
9. create draft snapshot
10. review manifest and provenance
11. approve snapshot
12. generate compatibility views
```

## 6. Clasificación de discrepancias

| Tipo | Acción |
|---|---|
| Formato distinto, semántica igual | aceptar con evidencia |
| Redondeo diferente | bloquear y resolver policy |
| Estudiante no mapeado | bloquear sección |
| Evaluación no declarada | bloquear snapshot |
| Campo legacy sin consumidor | documentar y decidir |
| Regla hardcodeada no representable | diseñar operador o mantener sección en legacy |
| PII adicional en output nuevo | bloquear |

## 7. Compatibilidad

El periodo de compatibilidad debe ser finito. Cada adapter legacy declara:

- versión introducida;
- consumidores conocidos;
- fecha/condición de retiro;
- warnings;
- owner.

No se permite que nuevos componentes dependan de rutas legacy.

## 8. Rollback y recuperación

Antes de publicar:

- volver al flujo legacy es posible mientras no se haya retirado;
- snapshots draft pueden descartarse.

Después de publicar:

- no se modifica el snapshot;
- se revoca o reemplaza la publicación;
- se crea un snapshot corregido;
- emails enviados requieren acción compensatoria.

## 9. Criterio de finalización

La migración se considera completa cuando:

- todos los publishers consumen snapshots;
- no hay datos reales bajo Git;
- no se usa RUT/nombre como identity key;
- las policies están materializadas y versionadas;
- los aliases legacy no tienen consumidores;
- los runbooks y pruebas de recuperación están aprobados.
