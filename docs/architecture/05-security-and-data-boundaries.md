# 05 — Seguridad, PII y límites de datos

## 1. Objetivo

Definir qué datos existen, dónde pueden almacenarse, quién puede consumirlos y qué
controles son obligatorios antes de incorporar portal, email o BI.

## 2. Clasificación

| Clase | Ejemplos | Git | Portal | Email logs | BI |
|---|---|---:|---:|---:|---:|
| Pública | schemas, documentación, fixtures sintéticos | Sí | Sí | Sí | Sí |
| Académica interna | rúbricas, configuración, políticas sin PII | Según caso | No por defecto | No | Agregada |
| PII | nombre, RUT, email, AVA user | No | Mínima | Enmascarada | No |
| Académica sensible | notas individuales, feedback, entregas | No | Solo propios | No | Agregada |
| Secreto | SMTP password, capability keys, tokens | No | Nunca en plaintext | Nunca | No |
| Estado operacional | messageId, receipts, retries, locks | No | No | Store privado | No |

## 3. Zonas de almacenamiento

### Código versionado

Permitido:

- código;
- schemas;
- ejemplos sintéticos;
- documentación;
- templates sin datos reales.

Prohibido:

- roster real;
- entregas;
- resultados individuales reales;
- previews de email;
- logs operacionales;
- claves;
- `.env`;
- exports privados.

### Datos privados de runtime

Deben vivir fuera del árbol Git o bajo una raíz inequívocamente ignorada. El sistema debe
verificar esa condición antes de procesar datos reales.

### Estado operacional

Debe ser persistente, con permisos restrictivos, locking y backup apropiado. No puede
vivir dentro de un directorio que se regenere o purgue como export.

## 4. Identidad

- `studentId` opaco y estable es la identidad técnica.
- Identificadores institucionales se guardan en un mapping privado.
- No se usa RUT, email, nombre ni hash simple de RUT como ID transversal.
- Un publisher solo recibe el mapping mínimo requerido.

## 5. Portal

### Amenazas mínimas

- enumeración de objetos;
- inspección de JSON/HTML en texto plano;
- brute-force online u offline;
- reuso de enlaces;
- fuga por logs/referrers;
- caché/CDN;
- publicación del directorio incorrecto;
- XSS en feedback o nombres;
- dependencia de terceros en la SPA.

### Controles obligatorios

- un artefacto por estudiante;
- ningún dataset global servible;
- sanitización/escaping estricto;
- CSP restrictiva;
- sin scripts remotos no pinneados;
- object IDs aleatorios no enumerables;
- hosting autenticado o AES-GCM por estudiante;
- capability de alta entropía en URL fragment para modo estático;
- `Referrer-Policy: no-referrer` cuando el hosting lo permita;
- `noindex`;
- política de caché explícita;
- receipt de publicación;
- revoke/purge con límites documentados.

### Lo que no cuenta como seguridad

- esconder secciones con CSS/JavaScript;
- publicar datos en plaintext y validar un código solo en frontend;
- PINs cortos con muchas iteraciones PBKDF2;
- rutas difíciles de adivinar sin cifrado;
- HTTPS sin autorización.

## 6. Email

### Amenazas mínimas

- destinatario equivocado;
- datos de un alumno enviados a otro;
- doble envío;
- cambio del contenido después de aprobación;
- filtración de previews/logs;
- credenciales SMTP expuestas;
- concurrencia;
- reintentos ambiguos.

### Controles obligatorios

- dry-run por defecto;
- preview exacto por destinatario;
- hash del plan aprobado;
- confirmación humana del conteo y hash;
- idempotency key semántica;
- ledger durable;
- lock por batch/operación;
- validación de template antes del primer envío;
- clasificación de errores;
- PII enmascarada en logs;
- secretos solo por secret store/variables de entorno;
- transporte de prueba en CI.

## 7. BI

### Amenazas mínimas

- grupos pequeños;
- inferencia por diferencias entre releases;
- combinación de dimensiones;
- min/max identificables;
- series históricas que revelen individuos;
- inclusión accidental de IDs.

### Controles obligatorios

- allow-list de dimensiones;
- mínimo de cohorte configurable;
- supresión primaria y complementaria;
- prohibición de dimensiones libres;
- revisión de disclosure risk para nuevas vistas;
- contrato de output que rechaza campos PII;
- release inmutable con provenance;
- tests de diferencia entre releases.

## 8. Logging

Los logs no incluyen:

- cuerpos de email;
- feedback;
- RUT completo;
- email completo;
- claves/capabilities;
- contenido de submissions.

Se permiten identificadores opacos, códigos de error, hashes no reversibles de payload y
referencias a `publicationId`.

## 9. Retención

Debe configurarse por clase de datos:

- working data;
- snapshots aprobados;
- portal deployments;
- email ledgers;
- receipts;
- logs;
- claves revocadas.

`purge` debe emitir un reporte de lo eliminado y de lo que no puede eliminar (por ejemplo,
correos enviados o copias ya descargadas).

## 10. Respuesta a incidentes

Se requieren runbooks para:

1. PII versionada por error.
2. Email enviado a destinatario incorrecto.
3. Portal publicado con datos cruzados.
4. Capability comprometida.
5. Release BI con riesgo de reidentificación.
6. Pérdida/corrupción del ledger.

Los runbooks deben distinguir:

- contención;
- evidencia;
- rotación/revocación;
- comunicación;
- corrección;
- prevención de recurrencia.

## 11. Gate de seguridad

Cualquier publisher falla cerrado cuando:

- la fuente no tiene clasificación;
- se detecta PII no autorizada;
- el snapshot no está aprobado;
- la audiencia no coincide con la proyección;
- falta configuración segura de hosting/SMTP;
- el store operacional no está disponible;
- el plan aprobado no coincide con el hash actual.
