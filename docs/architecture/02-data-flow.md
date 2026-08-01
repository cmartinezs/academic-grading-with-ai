# 02 — Diagrama de flujo de datos

```text
[students.json]──▶[config.json sección]◀──prepare-evaluation.sh
                                      │
[results/*.md revisados]──▶export-publication-data.py──▶[results.json] ◀── CANÓNICA
                                                        │  + results.schema.json
     ┌───────────────┬────────────────┴────────────────┐
     ▼               ▼                                 ▼
grades.json/    relational-3fn/ (25 tablas+vistas)   (Node, opcional)
evaluations.json  + validador                         │
(indexes)         (modelo de información)             ▼
                                                    student-results-web/ (portal)
                                                            │
                                                            ▼
                                                    exports/email/ (destinatarios,
                                                    dry-run, envío, logs, estado)
```

## Capas del modelo 3FN por consumidor

```text
canonical results.json
        │  export-relational-3fn.sh (determinista)
        ▼
┌─ TABLAS TRANSACCIONALES (25) ── uso interno, PII, nunca públicas
│
├─ VISTAS DE CONSULTA ── docente
│
├─ VISTA ESTUDIANTE ── student_portal.json → portal (fragmento por estudiante)
│
└─ VISTAS BI ── directiva (solo agregados, celdas n < umbral suprimidas)
```

## Gates de validación (ADR-0006)

| Paso | Schema | Fallo = pipeline se detiene |
|---|---|---|
| Parse de results | `results.schema.json` | export-publication-data |
| Config de sección | `section-config.schema.json` | prepare/init |
| Export 3FN | `bundle.schema.json`, `bi.schema.json` | export-relational-3fn |
| Portal | `student-portal.schema.json` | build-student-results-web |
| Email | contrato recipients + estado | build-recipients / send |
