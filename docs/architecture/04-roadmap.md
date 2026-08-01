# 04 — Roadmap de implementación, gates y riesgos

Este roadmap reemplaza el orden C1–C6 anterior. La seguridad de datos y el modelo de
publicación se resuelven antes de implementar 3FN, portal o email.

## C0 — Threat model, PII y almacenamiento

### Alcance

- Clasificación de datos.
- Identidad opaca de estudiantes.
- Separación `private` / `publications` / `state`.
- Reglas de `.gitignore` y pre-commit para PII/secretos.
- Fixtures completamente sintéticos.
- Política de retención.
- Threat model de portal, email y BI.

### Aceptación

- Ningún fixture contiene datos reales.
- RUT, email y submissions quedan fuera de Git.
- El sistema detecta un workspace mal ubicado o con PII versionable y falla cerrado.
- Existe una matriz de datos por audiencia y propósito.
- ADR-0007 y ADR-0008 están aprobados.

## C1 — Publication Snapshot y lifecycle

### Alcance

- Namespace por `sectionId/publicationId`.
- Manifest, hashes, provenance y versiones.
- Build en staging temporal y promoción atómica.
- Estados `draft/reviewed/approved/published/superseded/corrected/revoked`.
- Compatibilidad controlada para `grades.json` y `evaluations.json`.
- Gates sintácticos y semánticos.

### Depende de

C0.

### Aceptación

- Dos secciones no pueden sobrescribirse.
- Una corrección crea un nuevo `publicationId`.
- Un snapshot aprobado es inmutable.
- Un build fallido no deja una publicación parcial.
- El manifest verifica todos los hashes.
- Los builders puros son reproducibles con entradas y versiones fijas.

## C2 — Grade Policy Engine

### Alcance

- `grade-policy.json` tipado y versionado.
- Registro cerrado de operadores.
- Escalas, ponderaciones, faltantes, ajustes, bonos, reemplazos, caps y redondeo.
- Validación de referencias y conflictos.
- Policy snapshot dentro de cada publicación.
- Suite de conformidad con casos límite.

### Depende de

C1.

### Aceptación

- Ninguna expresión textual libre se evalúa.
- Operadores desconocidos fallan cerrado.
- Los pesos tienen una única autoridad.
- El orden de aplicación es explícito.
- Cada publicación puede reconstruir exactamente la policy aplicada.
- Los resultados coinciden con fixtures de FPY1101 donde la semántica es equivalente.

## C3 — Email prepare/approve/execute

### Alcance

- Join mínimo con roster privado.
- Generación de plan, previews y `previewHash`.
- Aprobación humana ligada al hash.
- Ledger durable con locking y escrituras atómicas.
- Idempotency key semántica.
- Taxonomía de errores SMTP.
- Reanudación segura.
- Templates versionados.

### Depende de

C1; C2 cuando el correo incluya resultados calculados por policy.

### Aceptación

- Dry-run es el comportamiento por defecto.
- `execute` rechaza un plan no aprobado o modificado.
- Dos procesos no pueden enviar el mismo destinatario simultáneamente.
- Reiniciar el equipo no elimina el conocimiento de envíos previos.
- Error de autenticación SMTP detiene el batch.
- Error individual transitorio no duplica otros envíos.
- Logs no contienen cuerpos ni destinatarios completos.

## C4 — Portal seguro

### Alcance

- Proyección individual independiente de 3FN.
- Modo hosting autenticado.
- Modo estático cifrado con AES-GCM y capability de alta entropía.
- Object IDs no enumerables.
- CSP, `noindex`, cache policy y checklist de hosting.
- Publish/revoke/purge con receipts.
- Rotación por publicación.

### Depende de

C1 y C0; C2 cuando muestre notas calculadas.

### Aceptación

- No existe dataset global servible.
- Inspeccionar el HTML/JSON descargado sin capability no revela datos.
- Códigos cortos o RUT no se aceptan como secreto.
- El fragmento de URL no se envía al servidor.
- `revoke` y `purge` documentan sus límites frente a caché/descargas.
- La publicación falla si el modo de hosting no cumple sus precondiciones.

## C5 — Proyecciones docente y BI

### Alcance

- Contrato teacher-audit.
- Port/adaptación del export relacional solo si existe consumidor concreto.
- Contrato BI separado.
- Allow-list de dimensiones.
- Cohorte mínima, supresión primaria/complementaria y controles de inferencia.
- Releases BI inmutables.

### Depende de

C1 y C2.

### Aceptación

- Portal y email no dependen del 3FN.
- La salida docente y BI viven en árboles separados.
- La equivalencia con FPY1101 se valida semánticamente, no por copiar 25 tablas.
- BI contiene cero PII directa.
- Nuevas dimensiones requieren revisión de disclosure risk.
- Comparar dos releases no permite inferir celdas suprimidas mediante diferencias triviales.

## C6 — Convenciones y documentación operacional

### Alcance

- `support/` y `raw/` como convenciones opcionales.
- `CLAUDE.md` como guía opcional, sin secretos ni rutas locales.
- Validación de clasificación de contenido.
- Runbooks de corrección, revocación, incidente de email y fuga de portal.

### Depende de

C0.

### Aceptación

- Las carpetas no se crean vacías por defecto.
- Contenido privado queda explícitamente excluido de Git.
- Los runbooks distinguen rollback técnico de acción compensatoria.

## C7 — Discovery asistido por LLM

### Alcance

- Proponer instancias de `section-config` y `grade-policy` compatibles con schemas existentes.
- Diff determinista.
- Aprobación humana.
- Provenance del modelo/prompt/inputs.

### Depende de

C1 y C2 estabilizados.

### Aceptación

- Discovery no crea schemas, operadores ni parsers ejecutables.
- Ningún borrador entra al pipeline sin aceptación explícita.
- Repetir el pipeline determinista después de aprobar una config no invoca al LLM.

## Orden recomendado

```text
C0 → C1 → C2 → (C3 ∥ C4) → C5 → C6 → C7
```

C6 puede adelantarse parcialmente después de C0. C5 puede diferirse si no existe un
consumidor docente/BI real. C7 no es parte del MVP operacional.

## Criterios globales

- Ningún dato privado se versiona.
- No existe identidad técnica basada en RUT o nombre.
- Los builders puros son reproducibles; los ejecutores son idempotentes y auditables.
- Cada publicación es inmutable y trazable.
- Toda proyección declara audiencia y clasificación de datos.
- Los gates validan schema e invariantes de negocio.
- Node.js ausente no rompe el core Python.
- Un failure no deja snapshots parciales ni estados de envío ambiguos.

## Riesgos y tratamiento

| Riesgo | Tratamiento | Recuperación/compensación |
|---|---|---|
| PII en Git | separación física + scans + fixtures sintéticos | rotar secretos, remover historial, notificar según política |
| Sección equivocada | namespace + manifest + aprobación con resumen | nueva publicación; revocar la incorrecta |
| Snapshot parcial | staging + promoción atómica | descartar staging |
| Drift de policy | policy snapshot + hashes | crear publicación corregida |
| Email incorrecto | previewHash + ledger + confirmación | detener batch, comunicación correctiva; no existe rollback |
| Doble envío | idempotency key + lock + ledger durable | identificar afectados y compensar |
| Portal expuesto | cifrado/auth + capabilities + purge | revoke, rotación y comunicación; descargas previas no se revierten |
| Inferencia BI | policy de disclosure + releases inmutables | retirar release y publicar corrección |
| Complejidad 3FN | consumidor obligatorio + contrato por audiencia | diferir C5 |
| Sobre-generalización | perfil V1 explícito + extension points | rechazar casos fuera de perfil hasta diseñarlos |

## Definición de listo para comenzar código

- [ ] ADR-0001 a ADR-0011 aprobados.
- [ ] Threat model aprobado.
- [ ] Data boundary definido y probado con fixtures sintéticos.
- [ ] Contrato de policy cerrado.
- [ ] Perfil soportado V1 aceptado.
- [ ] Decisión de almacenamiento local/seguro tomada.
- [ ] Plan de migración desde rutas actuales definido.
