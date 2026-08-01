"""Legacy adapter: transforms the legacy export into canonical publication payloads.

- consumes the semantic output of ``export-publication-data.py``;
- maps RUT-based ids to opaque ``studentId``;
- removes PII from canonical contracts;
- preserves scores, grades, statuses and allowed feedback;
- does NOT introduce additional calculations;
- captures hashes and provenance for the snapshot.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

from .clock import Clock
from .errors import UnmappedStudentError
from .ids import attempt_id, validate_section_id
from .jsonutil import encode, sha256_bytes
from .legacy import LegacyExport
from .schemas import SCHEMA_VERSION

ADAPTER_NAME = "legacy-export-adapter"
ADAPTER_VERSION = "0.1.0"

# Legacy statuses preserved verbatim (the legacy export already normalizes them).
ALLOWED_STATUSES = frozenset(
    {"Evaluada", "En revisión", "Pendiente", "Observada", "Requiere conversación"}
)

# Keys that must never appear in canonical payloads (privacy gate, structural).
PII_KEYS = frozenset({"name", "rut", "email", "avaUser", "repoUrl", "resultPath", "studentName"})


def _subject_key() -> str:
    return "studentId"


class LegacyAdapter:
    """Deterministic adapter: legacy export + opaque identity mapping -> canonical payloads."""

    def __init__(
        self,
        legacy: LegacyExport,
        section_id: str,
        resolve_student_id: Callable[[str], Optional[str]],
        clock: Optional[Clock] = None,
        applied_migrations: Optional[list[str]] = None,
    ):
        self.legacy = legacy
        self.section_id = validate_section_id(section_id)
        self.resolve = resolve_student_id
        self.clock = clock or Clock()
        self.applied_migrations = list(applied_migrations or [])

    # -- identity ---------------------------------------------------------

    def build_mapping(self) -> dict[str, str]:
        """Map every legacy student rut to its opaque studentId (fail on unmapped)."""
        mapping: dict[str, str] = {}
        for student in self.legacy.students:
            rut = str(student.get("id") or student.get("rut") or "").strip()
            if not rut:
                continue
            student_id = self.resolve(rut)
            if student_id is None:
                raise UnmappedStudentError(
                    f"No opaque identity assigned for legacy student {rut}; "
                    "run c0-identity/c0-migrate before building."
                )
            mapping[rut] = student_id

        for result in self.legacy.results:
            rut = str(result.get("studentId") or "").strip()
            if not rut:
                continue
            if rut not in mapping:
                raise UnmappedStudentError(
                    f"Result references a student without opaque identity: {rut}."
                )
        return mapping

    # -- canonical payloads -------------------------------------------------

    def build_section(self, mapping: Mapping[str, str]) -> dict:
        course_name = self.legacy.course_id() or self.section_id
        assessment_ids = sorted(str(ev["id"]) for ev in self.legacy.evaluations)
        defaults = dict(self.legacy.effective_defaults())
        structural = {}
        if "evaluationType" in defaults:
            structural["evaluationType"] = defaults["evaluationType"]
        course_cfg = self.legacy.course.get("course") or {}
        term = None
        for key in ("term", "academicPeriod", "period", "semester"):
            if course_cfg.get(key):
                term = str(course_cfg[key])
                break
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "course": {
                "code": course_name,
                "title": self.legacy.course_title() or course_name,
            },
            "term": term,
            "defaults": structural,
            "assessmentIds": assessment_ids,
            "schemaVersions": {"canonical": SCHEMA_VERSION, "policy": SCHEMA_VERSION},
        }

    def build_subjects(self, mapping: Mapping[str, str]) -> dict:
        subjects = []
        for student in sorted(self.legacy.students, key=lambda item: str(item.get("id") or "")):
            rut = str(student.get("id") or student.get("rut") or "").strip()
            if not rut:
                continue
            subjects.append(
                {
                    "studentId": mapping[rut],
                    "academicState": {"status": "active"},
                    "refs": [],
                }
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "subjects": subjects,
        }

    def build_assessments(self) -> dict:
        assessments = []
        for evaluation in sorted(self.legacy.evaluations, key=lambda item: str(item.get("id") or "")):
            assessments.append(
                {
                    "assessmentId": str(evaluation["id"]),
                    "title": evaluation.get("title"),
                    "type": evaluation.get("type"),
                    "date": evaluation.get("date"),
                    "forms": sorted(evaluation.get("forms") or []),
                    "refs": [],
                }
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "assessments": assessments,
        }

    def build_results(self, mapping: Mapping[str, str]) -> dict:
        results = []
        for item in sorted(
            self.legacy.results,
            key=lambda it: (str(it.get("studentId") or ""), str(it.get("evaluationId") or "")),
        ):
            rut = str(item.get("studentId") or "").strip()
            assessment_id = str(item.get("evaluationId") or "").strip()
            student_id = mapping.get(rut, "")
            att = attempt_id(self.section_id, assessment_id, student_id)
            results.append(
                {
                    "studentId": student_id,
                    "assessmentId": assessment_id,
                    "attemptId": att,
                    "form": item.get("form"),
                    "status": item.get("status") or "Pendiente",
                    "score": item.get("score"),
                    "grade": item.get("grade"),
                    "components": list(item.get("ies") or []),
                    "feedback": item.get("finalFeedback") or None,
                    "evidenceRefs": [],
                }
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "results": results,
        }

    def build_policy(self) -> dict:
        defaults = dict(self.legacy.effective_defaults())
        policy_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "policySchemaVersion": SCHEMA_VERSION,
            "mode": "legacy-effective",
            "calculationAuthority": ADAPTER_NAME,
            "effectiveDefaults": defaults,
            "evaluationWeights": self.legacy.evaluation_weights(),
        }
        content = {
            "mode": policy_payload["mode"],
            "calculationAuthority": policy_payload["calculationAuthority"],
            "effectiveDefaults": policy_payload["effectiveDefaults"],
            "evaluationWeights": policy_payload["evaluationWeights"],
            "policySchemaVersion": policy_payload["policySchemaVersion"],
        }
        policy_payload["contentHash"] = sha256_bytes(encode(content))
        return policy_payload

    def build_canonical(self) -> dict[str, dict]:
        mapping = self.build_mapping()
        return {
            "canonical/section.json": self.build_section(mapping),
            "canonical/subjects.json": self.build_subjects(mapping),
            "canonical/assessments.json": self.build_assessments(),
            "canonical/results.json": self.build_results(mapping),
            "canonical/policy.json": self.build_policy(),
        }

    # -- provenance ---------------------------------------------------------

    def build_source_hashes(self, mapping: Mapping[str, str]) -> dict:
        sources = [dict(item) for item in self.legacy.source_hashes]
        subject_ids = sorted(mapping.values())
        sources.append(
            {
                "ref": "identity-store/subjects",
                "sha256": sha256_bytes(encode(subject_ids)),
            }
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "sources": sources,
        }

    def build_engine_provenance(self) -> dict:
        # Volatile build time lives in the manifest (builtAt), not here, so the
        # engine provenance is part of the logical content hash (P0 hashes).
        return {
            "schemaVersion": SCHEMA_VERSION,
            "engineVersion": ADAPTER_VERSION,
            "adapterVersion": ADAPTER_VERSION,
            "adapter": ADAPTER_NAME,
        }

    def build_migrations_provenance(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "sectionId": self.section_id,
            "appliedMigrations": self.applied_migrations,
        }

    def build_provenance(self, mapping: Mapping[str, str]) -> dict[str, dict]:
        return {
            "provenance/source-hashes.json": self.build_source_hashes(mapping),
            "provenance/engine.json": self.build_engine_provenance(),
            "provenance/migrations.json": self.build_migrations_provenance(),
        }
