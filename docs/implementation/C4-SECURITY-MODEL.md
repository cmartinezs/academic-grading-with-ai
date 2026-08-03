# C4 Security Model

Threat model, decisiones criptográficas y fronteras de confianza del portal de
estudiantes.

## 1. Assets y adversarios

| Asset | Valor | Adversario principal |
|---|---|---|
| Nota/feedback individual | alto | estudiante ajeno, actor de red, host comprometido |
| Capability key | alto | actor con acceso al hosting, logs, caches |
| Object ID / capability URL | medio | enumerador de objetos |
| Proyección de otro estudiante | alto | estudiante autenticado ajeno |
| Ledger/receipts | medio | operador con acceso al state root |

## 2. Threat model del modo static-encrypted

| # | Amenaza | Mitigación |
|---|---|---|
| S1 | Enumeración de object IDs | 192 bits aleatorios, sin derivación de studentId, sin listado público |
| S2 | Leer payload sin clave | AES-256-GCM; sin plaintext académico en el árbol público |
| S3 | Brute-force de capability | 256 bits aleatorios; sin PIN/RUT/fechas como secreto |
| S4 | Tampering de ciphertext | GCM autentica; cualquier modificación falla el decrypt |
| S5 | Reuse key/nonce | nonce 96 bits aleatorio por cifrado, único por key, verificado |
| S6 | Fuga por logs/referrers | `Referrer-Policy: no-referrer`, `no-referrer` meta, capability nunca en logs |
| S7 | Caché/CDN | cache policy explícita; `private-no-store` en authenticated |
| S8 | XSS en feedback/nombres | render con `textContent`, CSP estricta, sin `innerHTML` |
| S9 | Dependencia de terceros | app estática sin scripts remotos, CDN, analytics o fonts remotas |
| S10 | Dataset global | un artefacto por estudiante; sin índice de students |
| S11 | Capability en query string | la clave viaja solo en `location.hash`, se limpia con `history.replaceState` |
| S12 | Directory listing | `directoryListingDisabled: true` en el hosting profile |

## 3. Threat model del modo authenticated

| # | Amenaza | Mitigación |
|---|---|---|
| A1 | Student A lee proyección de B | `authorizationModel: subject-bound`; `verify_subject_access` en cada lectura |
| A2 | Anonymous access | preflight + runtime rechazan anonymous |
| A3 | Listado global de projections | el adapter no expone endpoint de listado |
| A4 | Subject inexistente | denegación genérica sin distinguir "no existe" |
| A5 | Cross-student cache | `cachePolicy: private-no-store`; `crossStudentAccess: denied` |
| A6 | Adapter productivo no real | documentado como límite; fake adapter solo reference |

## 4. Decisiones criptográficas

- Algoritmo: AES-256-GCM vía `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- Key size: 256 bits (32 bytes), `secrets.token_bytes(32)`, base64url sin padding.
- Nonce: 96 bits (12 bytes), `secrets.token_bytes(12)`, único por key.
- AAD canónico: véase `C4-PORTAL-CONTRACT.md` §8 (no contiene studentId ni PII).
- Object ID: 192 bits (24 bytes), `secrets.token_bytes(24)`, base64url sin padding.
- Prohibido: ECB, CBC sin autenticación, XOR, criptografía propia, snippets copiados,
  fallbacks inseguros. Solo se usa el `AESGCM` del paquete `cryptography`.
- Interoperabilidad: Python AESGCM y Node WebCrypto (`AES-GCM`, 256 bits) son
  interoperables (nonce + AAD + ciphertext|tag en el mismo layout).
- Rotación: una key comprometida requiere un **nuevo release** con nuevas keys y object
  IDs; no se rota la key dentro del mismo release aprobado.

## 5. Frontera de confianza del navegador

- El navegador es el trust boundary final del modo static-encrypted.
- La app descifra localmente con Web Crypto (`crypto.subtle.importKey` +
  `decrypt` con `AES-GCM`).
- La capability key vive solo en `location.hash` en memoria, se limpia con
  `history.replaceState` y nunca se persiste en `localStorage`/`sessionStorage`.
- La app no realiza solicitudes adicionales tras cargar `metadata.json` y `payload.enc`.
- Los errores se muestran de forma genérica; la capability no aparece en mensajes.

## 6. Almacenamiento y permisos

| Zona | Permisos | Contenido |
|---|---|---|
| `private_root/portal/plans/**` | 0700 dir / 0600 file | plan, capability manifest, projections, public bundle |
| `state_root/portal/portal-ledger.sqlite3` | 0600 | ledger (sin keys ni payload) |
| `state_root/portal/receipts/` | 0700 dir / 0600 file | receipts (sin keys ni PII) |
| `state_root/portal/recovery/` | 0700 dir / 0600 file | recovery markers (sin keys) |
| `state_root/portal/deployments/**` | 0700 dir; 0644 solo archivos públicos cifrados dentro del deployment | artefactos publicados |
| Capability manifest privado | 0600 | studentId↔objectId↔key (private_root) |

## 7. Principios no negociables

1. Solo un Publication Snapshot aprobado puede originar un portal release.
2. Prepare nunca publica.
3. Publish requiere aprobación humana explícita.
4. Publish usa exclusivamente el bundle aprobado.
5. Un byte modificado después de approval bloquea publish.
6. Snapshot revoked/corrected/superseded bloquea nuevos publishes.
7. No existe dataset global servible.
8. Cada estudiante tiene un artefacto independiente.
9. Object IDs no se derivan de studentId, RUT, email o nombre.
10. Capability keys no se derivan de secretos memorizables.
11. RUT, email y nombre no aparecen en paths públicos.
12. Capability keys no aparecen en logs, receipts o SQLite.
13. No existe plaintext académico sensible en el árbol público.
14. La clave viaja solo en `location.hash`.
15. La clave no aparece en query string.
16. No existen analytics, pixels o scripts externos.
17. No usar `innerHTML` para contenido académico.
18. No implementar criptografía propia.
19. No usar ECB, CBC sin autenticación ni XOR.
20. No reutilizar key/nonce.
21. Revoke no promete recuperar copias descargadas.
22. Purge no promete borrar caches fuera del control del publisher.
23. No existe `--force`.
24. No existe auto-approval.
25. Fixtures y capabilities de tests son completamente sintéticos.
26. C0–C3 deben permanecer verdes.

## 8. Hosting gates (preflight fail-closed)

Un publisher falla cerrado si:

- el hosting profile es inválido o no cumple su modo (TLS, directory listing, headers,
  cache policy, authorization model);
- el snapshot no está aprobado o está terminal;
- el bundle aprobado no coincide con el releaseHash;
- el estado operacional (ledger) no está disponible;
- el plan aprobado difiere del plan actual;
- el adapter authenticated no puede autenticar al subject.

## 9. Fuera de alcance del modelo

- Integración real Firebase/Supabase/Cloudflare (límite documentado del modo
  authenticated en C4 V1).
- Service workers, analytics, fonts remotas, distribution por email automática.
- Cifrado-at-rest del state root (se protege por permisos 0700/0600 y backup).
