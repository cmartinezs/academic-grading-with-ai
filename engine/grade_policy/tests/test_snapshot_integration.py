"""C2 <-> C1 publication snapshot integration and failure-injection suite.

Exercises ``builder.build_draft`` with ``grade_policy_source`` set: the
canonical must gain the three C2 payloads, the manifest must list and hash
them, verification must be mode-aware, the review/approve flow must carry
them, and every failure path must leave no partial staging behind.

All data is synthetic; no PII and no real snapshots.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from grade_policy.errors import GradePolicyError, SchemaValidationError, UsageError

from publication import builder, verify
from publication.clock import Clock
from publication.hashing import encode, sha256_bytes

SECTION = "FP2111-S1"
RUT_A = "11111111-1"
RUT_B = "22222222-2"

DEFAULT_STUDENTS = [
    {"id": RUT_A, "rut": RUT_A, "name": "Ana Soto"},
    {"id": RUT_B, "rut": RUT_B, "name": "Bruno Rojas"},
]

DEFAULT_EVALUATIONS = [
    {"id": "ev1", "title": "EV1 - P1", "weight": 60, "type": "evaluacion", "forms": ["A", "B"]},
    {"id": "ev2", "title": "EV2 - P2", "weight": 40, "type": "examen"},
]

DEFAULT_RESULTS = [
    {"studentId": RUT_A, "evaluationId": "ev1", "form": "A", "status": "Evaluada",
     "score": 70.0, "grade": 5.5, "resultPath": "x", "finalFeedback": "Buen trabajo",
     "ies": [{"id": "a1", "weightPercent": 100.0, "awardedPercent": 70.0}]},
    {"studentId": RUT_A, "evaluationId": "ev2", "form": "A", "status": "Pendiente",
     "score": None, "grade": None, "resultPath": "x", "finalFeedback": "", "ies": []},
    {"studentId": RUT_B, "evaluationId": "ev1", "form": "B", "status": "Evaluada",
     "score": 55.0, "grade": 4.0, "resultPath": "x", "finalFeedback": "Mejorable", "ies": []},
    {"studentId": RUT_B, "evaluationId": "ev2", "form": "B", "status": "En revisión",
     "score": None, "grade": None, "resultPath": "x", "finalFeedback": "", "ies": []},
]

DEFAULT_COURSE = {
    "course": {"name": SECTION, "title": "Fundamentos de Programacion"},
    "defaults": {
        "approvalThreshold": 60,
        "grading": {"minGrade": 1, "passingGrade": 4, "maxGrade": 7, "passingPercent": 60},
        "presentationWeight": 60,
        "examWeight": 40,
    },
}

C2_RELS = ("canonical/policy.json", "canonical/outcomes.json", "canonical/traces.json")


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def force_rmtree(root: Path) -> None:
    if not root.exists():
        return
    shutil.rmtree(root, ignore_errors=True)


def c2_policy(assessments=("ev1", "ev2"), missing_policy: str = "zero") -> dict:
    return {
        "schemaVersion": "1.0.0",
        "policyId": "c2-integration",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": list(assessments),
        "stages": {
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [
                    {"ref": "ev1", "weight": "0.6"},
                    {"ref": "ev2", "weight": "0.4"},
                ],
                "missingPolicy": missing_policy,
            },
            "final": {
                "id": "final",
                "phase": "finalization",
                "operator": "round",
                "inputs": [{"ref": "w"}],
                "params": {"decimalPlaces": 2, "mode": "halfUp"},
            },
        },
        "resultStageId": "final",
    }


class C2SnapshotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="c2-int-"))
        self.legacy = self.base / "legacy"
        self.roots = self.base / "roots"
        self.env = {
            "ACADGRAD_PRIVATE_ROOT": str(self.roots / "priv"),
            "ACADGRAD_STATE_ROOT": str(self.roots / "state"),
            "ACADGRAD_PUBLICATIONS_ROOT": str(self.roots / "pub"),
            "ACADGRAD_TEMP_ROOT": str(self.roots / "tmp"),
            "SOURCE_DATE_EPOCH": "1700000000",
        }
        self.policy_file = self.base / "policy.json"
        self.write_legacy()
        self.ensure_identity([RUT_A, RUT_B])

    def tearDown(self) -> None:
        force_rmtree(self.base)

    # -- fixtures -----------------------------------------------------------

    def write_legacy(self) -> None:
        write(self.legacy / "manifest.json", {"course": {"id": SECTION}, "schemaVersion": 1})
        write(self.legacy / "course/course.json", DEFAULT_COURSE)
        write(self.legacy / "course/students.json", {"items": DEFAULT_STUDENTS})
        write(self.legacy / "course/evaluations.json", {"items": DEFAULT_EVALUATIONS})
        write(self.legacy / "course/results.json", {"items": DEFAULT_RESULTS})
        write(self.legacy / "course/course-summary.json", {"students": 2, "evaluations": 2})

    def ensure_identity(self, ruts) -> None:
        from c0.identity import IdentityStore

        store = IdentityStore(self.roots / "state" / "identity")
        store.ensure_many(
            [
                {"external": {"rut": rut}, "display_name": f"S {rut}"}
                for rut in ruts
            ]
        )

    def ctx(self, pub: str = "pub_c2", **kwargs) -> builder.BuildContext:
        kwargs.setdefault("legacy_source", self.legacy)
        return builder.BuildContext.resolve(
            self.base,
            SECTION,
            publication_id=pub,
            env=self.env,
            clock=Clock(env=self.env),
            **kwargs,
        )

    def build(self, pub: str = "pub_c2", **kwargs):
        ctx = self.ctx(pub, **kwargs)
        return ctx, builder.build_draft(ctx)

    def write_policy(self, policy_doc: dict) -> Path:
        write(self.policy_file, policy_doc)
        return self.policy_file

    def canonical(self, ctx) -> dict:
        return {
            rel: json.loads((ctx.staging_dir() / rel).read_text(encoding="utf-8"))
            for rel in ("canonical/subjects.json", "canonical/assessments.json",
                        "canonical/results.json", "canonical/section.json", "canonical/policy.json")
        }

    def subject_ids(self, ctx) -> list[str]:
        subs = json.loads((ctx.staging_dir() / "canonical/subjects.json").read_text(encoding="utf-8"))
        return sorted(s.get("studentId") for s in subs.get("subjects", []))


class C2BuildTest(C2SnapshotTestCase):
    def test_build_with_policy_adds_c2_payloads(self) -> None:
        self.write_policy(c2_policy())
        ctx, result = self.build(grade_policy_source=self.policy_file)
        staging = ctx.staging_dir()
        for rel in C2_RELS:
            self.assertTrue((staging / rel).exists(), rel)

        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        for rel in C2_RELS:
            self.assertIn(rel, manifest["files"], rel)
            entry = manifest["files"][rel]
            self.assertIn("sha256", entry)
            self.assertIn("classification", entry)
            self.assertEqual(entry["classification"], "RESTRICTED")
            self.assertEqual(entry["audience"], "grading")

        payload = json.loads((staging / "canonical/policy.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["mode"], "grade-policy-effective")
        self.assertEqual(payload["calculationAuthority"], "grade-policy-engine")
        self.assertIn("policyHash", payload)
        self.assertIsInstance(payload["policy"], dict)

    def test_content_hash_covers_c2_payloads(self) -> None:
        self.write_policy(c2_policy())
        ctx, result = self.build(grade_policy_source=self.policy_file)
        staging = ctx.staging_dir()
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        for rel in C2_RELS:
            digest = manifest["files"][rel]["sha256"]
            payload = json.loads((staging / rel).read_text(encoding="utf-8"))
            self.assertEqual(digest, sha256_bytes(encode(payload)), rel)

    def test_build_without_policy_has_no_c2_payloads(self) -> None:
        ctx, _ = self.build()
        staging = ctx.staging_dir()
        for rel in ("canonical/outcomes.json", "canonical/traces.json"):
            self.assertFalse((staging / rel).exists(), rel)

    def test_c2_build_is_deterministic(self) -> None:
        self.write_policy(c2_policy())
        _, first = self.build(pub="pub_deta", grade_policy_source=self.policy_file)
        _, second = self.build(pub="pub_detb", grade_policy_source=self.policy_file)
        self.assertEqual(first.content_hash, second.content_hash)

    def test_outcomes_match_expected_math(self) -> None:
        self.write_policy(c2_policy())
        ctx, _ = self.build(grade_policy_source=self.policy_file)
        outcomes = json.loads(
            (ctx.staging_dir() / "canonical/outcomes.json").read_text(encoding="utf-8")
        )
        by_subject = {o["subjectId"]: o for o in outcomes["subjectOutcomes"]}
        self.assertEqual(sorted(by_subject), self.subject_ids(ctx))
        for subject_id in self.subject_ids(ctx):
            outcome = by_subject[subject_id]
            self.assertEqual(outcome["status"], "finalized")
            self.assertEqual(outcome["value"]["unit"], "percent")
        expected = {"42", "33"}
        for subject_id in self.subject_ids(ctx):
            self.assertIn(by_subject[subject_id]["value"]["value"], expected)

    def test_review_approve_flow_carries_c2(self) -> None:
        self.write_policy(c2_policy())
        ctx, result = self.build(grade_policy_source=self.policy_file)
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        builder.approve_draft(ctx, result.review_hash, "approver-a", "approve", content_hash=result.content_hash)
        self.assertTrue(builder.is_approved_snapshot(ctx, "pub_c2"))
        root = ctx.sections_root() / SECTION / "pub_c2"
        for rel in C2_RELS:
            self.assertTrue((root / rel).exists(), rel)

    def test_verified_build_passes_mode_aware_gates(self) -> None:
        self.write_policy(c2_policy())
        ctx, _ = self.build(grade_policy_source=self.policy_file)
        report = verify.verify_snapshot(ctx.staging_dir(), section_id=SECTION, publication_id="pub_c2")
        self.assertTrue(report.passed(), report.summary())


class C2FailureInjectionTest(C2SnapshotTestCase):
    def assert_no_staging(self, ctx) -> None:
        self.assertFalse(ctx.staging_dir().exists())

    def test_missing_policy_file_fails_closed(self) -> None:
        ctx = self.ctx(grade_policy_source=self.base / "nope.json")
        with self.assertRaises(UsageError):
            builder.build_draft(ctx)
        self.assert_no_staging(ctx)

    def test_invalid_policy_json_fails_closed(self) -> None:
        (self.policy_file).write_text("{ not json", encoding="utf-8")
        ctx = self.ctx(grade_policy_source=self.policy_file)
        with self.assertRaises(SchemaValidationError):
            builder.build_draft(ctx)
        self.assert_no_staging(ctx)

    def test_assessment_missing_from_canonical_fails_closed(self) -> None:
        self.write_policy(c2_policy(assessments=("ev1", "ev3")))
        ctx = self.ctx(grade_policy_source=self.policy_file)
        with self.assertRaises(GradePolicyError):
            builder.build_draft(ctx)
        self.assert_no_staging(ctx)

    def test_fail_missing_policy_blocks_build(self) -> None:
        self.write_policy(c2_policy(missing_policy="fail"))
        ctx = self.ctx(grade_policy_source=self.policy_file)
        with self.assertRaises(GradePolicyError):
            builder.build_draft(ctx)
        self.assert_no_staging(ctx)

    def test_unknown_assessment_in_policy_blocks_build(self) -> None:
        self.write_policy(c2_policy(assessments=("ev1", "ev2", "ghost")))
        ctx = self.ctx(grade_policy_source=self.policy_file)
        with self.assertRaises(GradePolicyError):
            builder.build_draft(ctx)
        self.assert_no_staging(ctx)


class C2VerifyGateTest(C2SnapshotTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_policy(c2_policy())
        self.ctx, self.result = self.build(grade_policy_source=self.policy_file)
        self.staging = self.ctx.staging_dir()

    def tamper_outcomes(self, mutate) -> None:
        path = self.staging / "canonical/outcomes.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        write(path, doc)

    def test_orphan_outcome_detected(self) -> None:
        def mutate(doc):
            doc["subjectOutcomes"].append({"subjectId": "ghost-subject", "status": "finalized"})

        self.tamper_outcomes(mutate)
        report = verify.verify_snapshot(self.staging, section_id=SECTION, publication_id="pub_c2")
        self.assertFalse(report.passed())
        self.assertTrue(any("Orphan outcome" in m for m in report.gate_findings("G5-semantic")))

    def test_duplicate_outcome_detected(self) -> None:
        def mutate(doc):
            doc["subjectOutcomes"].append(dict(doc["subjectOutcomes"][0]))

        self.tamper_outcomes(mutate)
        report = verify.verify_snapshot(self.staging, section_id=SECTION, publication_id="pub_c2")
        self.assertFalse(report.passed())
        self.assertTrue(any("Duplicate outcome" in m for m in report.gate_findings("G5-semantic")))

    def test_trace_subject_mismatch_detected(self) -> None:
        path = self.staging / "canonical/traces.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["subjectTraces"].pop()
        write(path, doc)
        report = verify.verify_snapshot(self.staging, section_id=SECTION, publication_id="pub_c2")
        self.assertFalse(report.passed())
        self.assertTrue(
            any("do not match outcomes" in m for m in report.gate_findings("G5-semantic"))
        )

    def test_orphan_trace_detected(self) -> None:
        path = self.staging / "canonical/traces.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["subjectTraces"].append({"subjectId": "ghost-subject", "stages": []})
        write(path, doc)
        report = verify.verify_snapshot(self.staging, section_id=SECTION, publication_id="pub_c2")
        self.assertFalse(report.passed())
        self.assertTrue(any("Orphan trace" in m for m in report.gate_findings("G5-semantic")))

    def test_c2_verification_requires_c2_policy_fields(self) -> None:
        path = self.staging / "canonical/policy.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        del doc["policyHash"]
        write(path, doc)
        report = verify.verify_snapshot(self.staging, section_id=SECTION, publication_id="pub_c2")
        self.assertFalse(report.passed())
        self.assertTrue(
            any("missing 'policyHash'" in m for m in report.gate_findings("G5-semantic"))
        )


if __name__ == "__main__":
    unittest.main()
