# C1 — Contrato de Publication Snapshot

Especifica formatos e invariantes antes de escribir el builder. Los schemas JSON
(Draft 2020-12) viven en `engine/publication/schemas/`.

## 1. Identidad

- `sectionId`: section code estructural (p. ej. `CUR0001-001`). No es PII. Debe ser un
  segmento de path seguro: `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, sin `..`, sin `/`, sin
  `\`, sin caracteres de control, sin `-` inicial.
- `publicationId`: opaco, aleatorio, 128 bits: `pub_<hex>`. Nunca derivado de contenido,
  sección ni timestamps. Inyectable en tests. Patrón `^pub_[0-9a-f]{32}$` (en operación)
  o `^pub_[A-Za-z0-9]{1,64}$` (validación general).
- `studentId`: `stu_<hex>` 128 bits vía `c0.identity`. Única clave transversal.
- `attemptId`: estable dentro del snapshot, determinista:
  `att_` + sha256(sectionId|assessmentId|studentId) (primeros 16 bytes).
- `assessmentId`: id de evaluación legacy (`EV01`, ...) como referencia estable y no PII.

## 2. Contratos canónicos

Todos declaran `schemaVersion: "1.0.0"` y se serializan con la escritura JSON
determinista del §5.

### canonical/section.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "course": {"code": "CUR0001", "title": "Programación"},
  "term": null,
  "defaults": {"evaluationType": "regular"},
  "assessmentIds": ["EV01"],
  "schemaVersions": {"canonical": "1.0.0", "policy": "1.0.0"}
}
```

Invariante: no contiene pesos. `defaults` = defaults efectivos estructurales materializados.

### canonical/subjects.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "subjects": [
    {"studentId": "stu_...", "academicState": {"status": "active"}, "refs": []}
  ]
}
```

Invariante: sin `name`, `rut`, `email`, `avaUser`, `repoUrl`.

### canonical/assessments.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "assessments": [
    {"assessmentId": "EV01", "title": "Control 1", "type": "regular",
     "date": "2026-08-01", "forms": ["A", "B"]}
  ]
}
```

Invariante: sin pesos (autoridad en `policy.json`).

### canonical/results.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "results": [
    {"studentId": "stu_...", "assessmentId": "EV01", "attemptId": "att_...",
     "status": "Evaluada", "score": 85.0, "grade": 6.4, "components": [],
     "feedback": "texto", "evidenceRefs": ["evidence/EV01/att_..."]}
  ]
}
```

Invariantes: `studentId` opaco; sin `resultPath` con RUT/nombre; `score`/`grade`/`status`/
`feedback`/`components` preservados del export legacy.

### canonical/policy.json

```json
{
  "schemaVersion": "1.0.0",
  "policySchemaVersion": "1.0.0",
  "mode": "legacy-effective",
  "calculationAuthority": "legacy-export-adapter",
  "effectiveDefaults": {"approvalThreshold": 60},
  "evaluationWeights": {"EV01": 30},
  "contentHash": "<sha256>"
}
```

`contentHash` = sha256 de la serialización canónica de
{mode, calculationAuthority, effectiveDefaults, evaluationWeights, policySchemaVersion}.
No se evalúan expresiones ni operadores (C2).

## 3. Provenance

### provenance/source-hashes.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "sources": [
    {"ref": "legacy-export/results.json", "sha256": "<sha256>", "size": 123},
    {"ref": "identity-store/recordCount", "value": 42}
  ]
}
```

Invariante: refs sanitizados; ningún nombre de archivo que contenga RUT.

### provenance/engine.json

```json
{
  "schemaVersion": "1.0.0",
  "engineVersion": "0.1.0",
  "adapterVersion": "0.1.0",
  "adapter": "legacy-export-adapter",
  "builtAt": "2026-08-01T00:00:00Z"
}
```

### provenance/migrations.json

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "appliedMigrations": []
}
```

## 4. Approvals

### approvals/review.json

```json
{
  "schemaVersion": "1.0.0",
  "publicationId": "pub_...",
  "contentHash": "<sha256 exacto>",
  "reviewedBy": "user:reviewer-1",
  "reviewedAt": "2026-08-01T00:00:00Z",
  "status": "reviewed"
}
```

### approvals/publication-approval.json

```json
{
  "schemaVersion": "1.0.0",
  "publicationId": "pub_...",
  "contentHash": "<sha256 exacto>",
  "approvedBy": "user:approver-1",
  "approvedAt": "2026-08-01T00:00:00Z",
  "confirmation": "approve",
  "status": "approved"
}
```

Invariante: `reviewedBy`/`approvedBy` son IDs de auditoría; nunca emails. La aprobación
queda ligada al `contentHash` exacto.

## 5. Serialización determinista

```text
json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
```

- UTF-8; claves ordenadas; indentación estable; newline final.
- Sin timestamps implícitos; locale/timezone independientes.
- sha256 de cada archivo sobre los bytes realmente escritos.

## 6. Manifest

```json
{
  "schemaVersion": "1.0.0",
  "sectionId": "CUR0001-001",
  "publicationId": "pub_...",
  "status": "approved",
  "supersedesPublicationId": null,
  "correctsPublicationId": null,
  "contentHash": "<sha256>",
  "engineVersion": "0.1.0",
  "adapterVersion": "0.1.0",
  "policySnapshotVersion": "1.0.0",
  "createdAt": "2026-08-01T00:00:00Z",
  "approvedAt": "2026-08-01T00:00:00Z",
  "approvedBy": "user:approver-1",
  "files": {
    "canonical/section.json": {
      "classification": "internal", "audience": "internal",
      "size": 123, "sha256": "<sha256>"
    }
  }
}
```

Invariantes manifest:

- Todos los archivos declarados existen y su `size`/`sha256` son correctos.
- No hay archivos fuera de los declarados.
- `contentHash` reproducible sobre `canonical/*` + `provenance/*`.
- `supersedesPublicationId` y `correctsPublicationId` mutuamente exclusivos y ≠ propio id.
- Sin paths absolutos, RUT, email, secrets, hostnames personales, username ni capabilities.

## 7. Lifecycle ledger

Ubicación: `<state-root>/publications/<sectionId>/lifecycle-ledger.jsonl` (append-only).

```json
{"schemaVersion":"1.0.0","seq":1,"event":"created","publicationId":"pub_...","at":"...","actor":"..."}
{"schemaVersion":"1.0.0","seq":2,"event":"reviewed","publicationId":"pub_...","at":"...","actor":"user:reviewer-1"}
{"schemaVersion":"1.0.0","seq":3,"event":"approved","publicationId":"pub_...","at":"...","actor":"user:approver-1"}
{"schemaVersion":"1.0.0","seq":4,"event":"published","publicationId":"pub_...","receipt":"rcpt_...","at":"...","actor":"user:ops-1"}
{"schemaVersion":"1.0.0","seq":5,"event":"corrected","publicationId":"pub_A","byPublicationId":"pub_B","reason":"...","at":"...","actor":"user:ops-1"}
```

Estados derivados: `created → reviewed → approved → published` y terminales
`superseded | corrected | revoked` (gana el último evento por `seq`).

## 8. Vistas de compatibilidad

Cada vista declara:

- `sourcePublicationId`
- `schemaVersion`
- `generatedBy` (`publication-snapshot/compat/v1`)
- `canonicalSourceHash`

Vistas: `evaluations.json`, `grades.json` y bundle legacy `course/*` (course, students,
evaluations, results, course-summary). Se generan únicamente desde un snapshot aprobado,
con `compatibility --generate`; los aliases legacy requieren `--update-legacy-aliases`.

## 9. Exit codes CLI

- `0` éxito.
- `1` error de uso / estado inválido (por ejemplo, transición ilegal).
- `2` fallo de gate (schema, hash, identidad, privacidad) — fail-closed.

## 10. Invariantes globales

1. Un snapshot aprobado es inmutable (detectado por hashes y permisos read-only).
2. `results.json` canónico permanece dentro del snapshot.
3. Una corrección crea un `publicationId` nuevo.
4. Dos secciones nunca comparten namespace.
5. RUT/email/nombre nunca son claves técnicas.
6. Los canonical payloads usan `studentId` opaco.
7. Ningún publisher vuelve a parsear Markdown.
8. El export legacy continúa disponible.
9. Nuevos componentes no dependen de la ruta global legacy.
10. Un build fallido no deja publicación parcial.
11. Los schemas e invariantes fallan cerrado.
12. Los builders puros son reproducibles.
13. Timestamps/metadata volátil no contaminan el hash lógico.
14. Datos privados, publicaciones y estado operacional permanecen separados.
15. No se versiona ningún snapshot real; tests solo con datos sintéticos.
