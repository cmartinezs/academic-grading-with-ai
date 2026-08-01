"""C1 contract, integration and failure test suite (unittest, stdlib only).

Covers ids, schemas, adapter, manifest/determinism, staging/promotion,
review/approve, immutability, lifecycle, privacy gates and compatibility views.
All data is synthetic; no real snapshots are versioned.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from c0.identity import IdentityStore

from publication import builder, compat, schemas
from publication.adapter import PII_KEYS
from publication.clock import Clock
from publication.errors import (
    ConfirmationRequiredError,
    ContentHashMismatchError,
    DestinationExistsError,
    GateError,
    ImmutableSnapshotError,
    InvalidTransitionError,
    LedgerError,
    LegacyCourseMismatchError,
    MissingLegacyExportError,
    NotReviewedError,
    SchemaError,
    StagingExistsError,
    UnmappedStudentError,
)
from publication.ids import attempt_id, generate_publication_id, validate_publication_id, validate_section_id
from publication.jsonutil import compute_content_hash, encode, serialize
from publication.legacy import load_legacy_export
from publication.lifecycle import LifecycleLedger

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
    "course": {"name": SECTION, "title": "Fundamentos de Programación"},
    "defaults": {
        "approvalThreshold": 60,
        "grading": {"minGrade": 1, "passingGrade": 4, "maxGrade": 7, "passingPercent": 60},
        "presentationWeight": 60,
        "examWeight": 40,
    },
}


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def force_rmtree(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    shutil.rmtree(root, ignore_errors=True)


class C1TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="c1-test-"))
        self.legacy = self.base / "legacy"
        self.roots = self.base / "roots"
        self.env = {
            "ACADGRAD_PRIVATE_ROOT": str(self.roots / "priv"),
            "ACADGRAD_STATE_ROOT": str(self.roots / "state"),
            "ACADGRAD_PUBLICATIONS_ROOT": str(self.roots / "pub"),
            "ACADGRAD_TEMP_ROOT": str(self.roots / "tmp"),
            "SOURCE_DATE_EPOCH": "1700000000",
        }
        self.write_legacy()

    def tearDown(self) -> None:
        force_rmtree(self.base)

    # -- fixtures -----------------------------------------------------------

    def write_legacy(
        self,
        section: str = SECTION,
        students=None,
        evaluations=None,
        results=None,
        summary: dict | None = None,
    ) -> Path:
        write(self.legacy / "manifest.json", {"course": {"id": section}, "schemaVersion": 1})
        write(self.legacy / "course/course.json", DEFAULT_COURSE if evaluations is None else DEFAULT_COURSE)
        write(self.legacy / "course/students.json", {"items": students if students is not None else DEFAULT_STUDENTS})
        write(
            self.legacy / "course/evaluations.json",
            {"items": evaluations if evaluations is not None else DEFAULT_EVALUATIONS},
        )
        write(self.legacy / "course/results.json", {"items": results if results is not None else DEFAULT_RESULTS})
        write(self.legacy / "course/course-summary.json", summary or {"students": 2, "evaluations": 2})
        return self.legacy

    def ensure_identity(self, ruts, state_root: Path | None = None, display="S") -> None:
        store = IdentityStore((state_root or self.roots / "state") / "identity")
        store.ensure_many(
            [
                {"external": {"rut": rut}, "display_name": f"{display} {rut}"}
                for rut in ruts
            ]
        )

    def ctx(self, pub: str = "pub_a", section: str = SECTION, **kwargs) -> builder.BuildContext:
        env = kwargs.pop("env", self.env)
        return builder.BuildContext.resolve(
            self.base,
            section,
            publication_id=pub,
            env=env,
            clock=Clock(env=env),
            legacy_source=kwargs.pop("legacy_source", self.legacy),
            **kwargs,
        )

    def prep(self, pub: str = "pub_a", section: str = SECTION, ruts=(RUT_A, RUT_B)) -> builder.BuildContext:
        self.ensure_identity(ruts)
        return self.ctx(pub, section=section)

    def approve_flow(self, pub: str = "pub_a", section: str = SECTION, ruts=(RUT_A, RUT_B), **kwargs):
        ctx = self.prep(pub, section=section, ruts=ruts)
        result = builder.build_draft(ctx, **kwargs)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        dest = builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")
        return ctx, result.content_hash, dest

    def approved(self, ctx, pub) -> bool:
        return builder.approved_snapshot_exists(ctx, pub) and builder.is_approved_snapshot(ctx, pub)


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------


class IdsTest(C1TestCase):
    def test_validate_section_rejects_path_traversal(self):
        for bad in ("../evil", "a/b", "..", ".", "a\\b", "a/b/.."):
            with self.assertRaises(Exception):
                validate_section_id(bad)

    def test_validate_section_accepts_valid(self):
        for good in ("FP2111-S1", "A.1", "seccion_2", "x"):
            self.assertEqual(validate_section_id(good), good)

    def test_publication_id_unique(self):
        self.assertNotEqual(generate_publication_id(), generate_publication_id())

    def test_publication_id_injectable(self):
        self.assertEqual(self.prep(pub="pub_injected").publication_id, "pub_injected")
        with self.assertRaises(Exception):
            self.ctx(pub="../escape")

    def test_attempt_id_deterministic(self):
        self.assertEqual(attempt_id("S1", "e1", "stu_1"), attempt_id("S1", "e1", "stu_1"))
        self.assertNotEqual(attempt_id("S1", "e1", "stu_1"), attempt_id("S2", "e1", "stu_1"))


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class SchemasTest(C1TestCase):
    def test_schema_valid_documents(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        staging = ctx.staging_dir()
        for rel in ("manifest.json", "canonical/results.json", "provenance/engine.json"):
            payload = json.loads((staging / rel).read_text(encoding="utf-8"))
            self.assertEqual(schemas.validate_document(rel, payload), [])

    def test_schema_invalid_document(self):
        errors = schemas.validate_document("manifest.json", {"schemaVersion": "1.0.0", "status": "nope"})
        self.assertTrue(errors)

    def test_schema_unknown_major(self):
        with self.assertRaises(SchemaError):
            schemas.require_supported_major("2.0.0")
        with self.assertRaises(SchemaError):
            schemas.require_supported_major("garbage")


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------


class AdapterTest(C1TestCase):
    def test_adapter_full_mapping(self):
        ctx = self.prep()
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        subjects = [s["studentId"] for s in canonical["canonical/subjects.json"]["subjects"]]
        self.assertEqual(len(subjects), 2)
        for student_id in subjects:
            self.assertRegex(student_id, r"^stu_[A-Za-z0-9]{16,}$")

    def test_adapter_unmapped_blocked(self):
        self.ensure_identity([RUT_A])
        ctx = self.ctx()
        with self.assertRaises(UnmappedStudentError):
            builder.build_draft(ctx)

    def test_old_new_semantic_equivalence(self):
        ctx = self.prep()
        store = IdentityStore(self.roots / "state/identity")
        reverse = {
            identity.student_id: identity.external_identifiers.get("rut")
            for identity in store.all()
        }
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        results = canonical["canonical/results.json"]["results"]
        legacy_by = {
            (r["studentId"], r["evaluationId"]): r for r in DEFAULT_RESULTS
        }
        self.assertEqual(len(results), 4)
        for result in results:
            rut = reverse[result["studentId"]]
            legacy = legacy_by[(rut, result["assessmentId"])]
            self.assertEqual(result["score"], legacy["score"])
            self.assertEqual(result["grade"], legacy["grade"])
            self.assertEqual(result["status"], legacy["status"])
            self.assertEqual(result["feedback"] or "", legacy["finalFeedback"] or "")


# ---------------------------------------------------------------------------
# manifest / determinism
# ---------------------------------------------------------------------------


class ManifestTest(C1TestCase):
    def test_manifest_complete_and_verify_ok(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        report = builder.verify(ctx, "staging")
        self.assertTrue(report.passed(), [f.message for f in report.findings])

    def test_manifest_extra_file_detected(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        write(ctx.staging_dir() / "rogue.json", {"unexpected": True})
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G7-manifest"))

    def test_manifest_wrong_hash_detected(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        (ctx.staging_dir() / "canonical/results.json").write_text('{"results": []}\n', encoding="utf-8")
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G7-manifest"))

    def test_manifest_size_mismatch_detected(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        path = ctx.staging_dir() / "canonical/results.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n//tamper", encoding="utf-8")
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G7-manifest"))

    def test_content_hash_reproducible_across_epochs(self):
        self.ensure_identity((RUT_A, RUT_B))
        env1 = {**self.env, "SOURCE_DATE_EPOCH": "1700000000"}
        env2 = {**self.env, "SOURCE_DATE_EPOCH": "1700099999"}
        r1 = builder.build_draft(self.ctx("pub_a", env=env1))
        builder.discard_staging(self.ctx("pub_a", env=env1))
        r2 = builder.build_draft(self.ctx("pub_b", env=env2))
        self.assertEqual(r1.content_hash, r2.content_hash)

    def test_serialize_sorted_keys_deterministic(self):
        left = {"z": 1, "a": [3, 1, 2], "n": {"x": 1, "y": 2}}
        right = {"a": [3, 1, 2], "n": {"y": 2, "x": 1}, "z": 1}
        self.assertEqual(encode(left), encode(right))
        self.assertEqual(serialize(left), serialize(right))


# ---------------------------------------------------------------------------
# staging / promotion
# ---------------------------------------------------------------------------


class StagingTest(C1TestCase):
    def test_build_failure_no_publication(self):
        ctx = self.prep()
        builder.discard_staging(ctx)
        (ctx.staging_dir()).unlink(missing_ok=True)
        legacy_dir = Path(tempfile.mkdtemp(prefix="c1-legacy-missing-"))
        self.addCleanup(force_rmtree, legacy_dir)
        bad_ctx = builder.BuildContext.resolve(
            self.base, SECTION, publication_id="pub_missing", env=self.env,
            clock=Clock(env=self.env), legacy_source=legacy_dir,
        )
        with self.assertRaises(MissingLegacyExportError):
            builder.build_draft(bad_ctx)
        self.assertFalse((self.roots / "pub/sections" / SECTION).exists())

    def test_write_failure_partial_staging_no_snapshot(self):
        ctx = self.prep()
        with mock.patch.object(builder, "write_json", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                builder.build_draft(ctx)
        self.assertFalse((self.roots / "pub/sections" / SECTION).exists())

    def test_crash_pre_rename_no_destination(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        with mock.patch.object(builder.os, "rename", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")
        self.assertFalse(ctx.destination_dir().exists())
        self.assertTrue(ctx.staging_dir().is_dir())

    def test_existing_destination_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        ctx.destination_dir().mkdir(parents=True, exist_ok=True)
        with self.assertRaises(DestinationExistsError):
            builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")

    def test_dry_run_writes_nothing(self):
        ctx = self.prep()
        result = builder.build_draft(ctx, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertFalse(ctx.staging_dir().exists())
        self.assertFalse((self.roots / "pub/sections" / SECTION).exists())

    def test_discard_staging(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        self.assertTrue(ctx.staging_dir().is_dir())
        self.assertTrue(builder.discard_staging(ctx))
        self.assertFalse(ctx.staging_dir().exists())
        self.assertFalse(builder.discard_staging(ctx))


# ---------------------------------------------------------------------------
# review / approve
# ---------------------------------------------------------------------------


class ReviewApproveTest(C1TestCase):
    def test_review_bound_to_hash(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        self.assertTrue((ctx.staging_dir() / "approvals/review.json").is_file())

    def test_review_wrong_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        wrong = "0" * 64
        with self.assertRaises(ContentHashMismatchError):
            builder.review_draft(ctx, wrong, "reviewer-a")

    def test_change_after_review_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        (ctx.staging_dir() / "canonical/results.json").write_text('{"results": []}\n', encoding="utf-8")
        with self.assertRaises(ContentHashMismatchError):
            builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")

    def test_approve_without_review(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        with self.assertRaises(NotReviewedError):
            builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")

    def test_approval_requires_confirmation(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        with self.assertRaises(ConfirmationRequiredError):
            builder.approve_draft(ctx, result.content_hash, "approver-a", "")

    def test_approve_wrong_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        with self.assertRaises(ContentHashMismatchError):
            builder.approve_draft(ctx, "f" * 64, "approver-a", "approve")


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------


class ImmutabilityTest(C1TestCase):
    def test_tampering_after_approval_detected(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        path = dest / "canonical/results.json"
        os.chmod(path, 0o600)
        path.write_text('{"results": []}\n', encoding="utf-8")
        report = builder.verify(ctx, "approved")
        self.assertFalse(report.passed())

    def test_rebuild_same_id_rejected(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        with self.assertRaises(ImmutableSnapshotError):
            builder.build_draft(ctx)

    def test_revocation_keeps_snapshot(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        ledger = ctx.ledger()
        ledger.append("revoked", "pub_a", actor="ops", reason="irregular")
        self.assertTrue(dest.is_dir())
        report = builder.verify(ctx, "approved")
        self.assertTrue(report.passed(), [f.message for f in report.findings])


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


class LifecycleTest(C1TestCase):
    def _approved_ledger(self, pub: str):
        ledger = LifecycleLedger(self.roots / "state", SECTION, clock=Clock(env=self.env))
        ledger.append("created", pub, actor="system")
        ledger.append("reviewed", pub, actor="reviewer-a")
        ledger.append("approved", pub, actor="approver-a")
        return ledger

    def test_published_requires_receipt(self):
        ledger = self._approved_ledger("pub_a")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("published", "pub_a", actor="ops")

    def test_published_requires_approved(self):
        ledger = LifecycleLedger(self.roots / "state", SECTION, clock=Clock(env=self.env))
        ledger.append("created", "pub_a", actor="system")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("published", "pub_a", actor="ops", receipt="r-1")

    def test_terminal_requires_by_publication(self):
        ledger = self._approved_ledger("pub_a")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("superseded", "pub_a", actor="ops")

    def test_corrected_new_publication_id(self):
        ctx_a, hash_a, _ = self.approve_flow("pub_a")
        ctx_b, hash_b, dest_b = self.approve_flow("pub_b", **{"corrects_publication_id": "pub_a"})
        self.assertNotEqual(ctx_a.publication_id, ctx_b.publication_id)
        ledger = ctx_b.ledger()
        ledger.append(
            "corrected",
            "pub_a",
            actor="ops",
            by_publication_id="pub_b",
            is_approved=lambda pid: self.approved(ctx_b, pid),
        )
        self.assertEqual(ledger.current_state("pub_a"), "corrected")

    def test_supersedes_corrects_exclusivity(self):
        self.approve_flow("pub_a")
        self.approve_flow("pub_b", **{"corrects_publication_id": "pub_a"})
        ctx = self.prep("pub_c")
        with self.assertRaises(GateError):
            builder.build_draft(ctx, supersedes_publication_id="pub_a", corrects_publication_id="pub_b")

    def test_invalid_transition_rejected(self):
        ledger = LifecycleLedger(self.roots / "state", SECTION, clock=Clock(env=self.env))
        ledger.append("created", "pub_a", actor="system")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("approved", "pub_a", actor="approver-a")

    def test_ledger_concurrent_append(self):
        ledger = LifecycleLedger(self.roots / "state", SECTION, clock=Clock(env=self.env))
        for pub in ("pub_a", "pub_b"):
            ledger.append("created", pub, actor="system")
            ledger.append("reviewed", pub, actor="reviewer-a")
            ledger.append("approved", pub, actor="approver-a")
        errors: list[Exception] = []

        def publish(pub: str):
            try:
                ledger.append("published", pub, actor="ops", receipt=f"rcpt-{pub}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=publish, args=(pub,)) for pub in ("pub_a", "pub_b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        events = ledger.read_events()
        seqs = [int(event["seq"]) for event in events]
        self.assertEqual(len(seqs), len(set(seqs)), "ledger seqs must be unique under concurrency")
        for event in events:
            self.assertEqual(event["schemaVersion"], "1.0.0")

    def test_terminal_from_published_allowed(self):
        ledger = self._approved_ledger("pub_a")
        ledger.append("published", "pub_a", actor="ops", receipt="r-1")
        ledger.append("superseded", "pub_a", actor="ops", by_publication_id="pub_b")
        self.assertEqual(ledger.current_state("pub_a"), "superseded")

    def test_correction_reference_must_be_approved(self):
        self.approve_flow("pub_a")
        ctx = self.prep("pub_c")
        with self.assertRaises(GateError):
            builder.build_draft(ctx, corrects_publication_id="pub_ghost")


# ---------------------------------------------------------------------------
# privacy / gates
# ---------------------------------------------------------------------------


class PrivacyTest(C1TestCase):
    def test_no_pii_keys_in_canonical(self):
        ctx = self.prep()
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        keys = set()

        def walk(payload):
            if isinstance(payload, dict):
                for k, v in payload.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(payload, list):
                for item in payload:
                    walk(item)

        for payload in canonical.values():
            walk(payload)
        self.assertEqual(keys & PII_KEYS, set())

    def test_pii_in_feedback_fails_gate(self):
        self.write_legacy(
            results=[
                {**DEFAULT_RESULTS[0], "finalFeedback": "contacte a alumno@mail.cl"}
            ]
        )
        ctx = self.prep()
        with self.assertRaises(GateError):
            builder.build_draft(ctx)

    def test_identity_integrity_fails_gate(self):
        ctx = self.prep()
        identity_file = self.roots / "state/identity/identity.json"
        identity_file.parent.mkdir(parents=True, exist_ok=True)
        identity_file.write_text("{corrupt", encoding="utf-8")
        with self.assertRaises(GateError):
            builder.build_draft(ctx)

    def test_canonical_uses_opaque_ids(self):
        ctx = self.prep()
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        results = canonical["canonical/results.json"]["results"]
        for result in results:
            self.assertRegex(result["studentId"], r"^stu_[A-Za-z0-9]{16,}$")
            self.assertRegex(result["attemptId"], r"^att_[A-Za-z0-9]{16}$")


# ---------------------------------------------------------------------------
# compatibility views
# ---------------------------------------------------------------------------


class CompatTest(C1TestCase):
    def test_compat_views_from_approved(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        written = compat.generate(ctx, update_legacy_aliases=True)
        self.assertIn("course/results.json", written)
        self.assertIn("legacy/grades.json", written)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        envelope = json.loads((view_root / "grades.json").read_text(encoding="utf-8"))
        self.assertEqual(envelope["sourcePublicationId"], "pub_a")
        self.assertEqual(envelope["generatedBy"], compat.GENERATED_BY)
        self.assertEqual(envelope["canonicalSourceHash"], content_hash)

    def test_compat_requires_approved(self):
        ctx = self.prep("pub_draft")
        builder.build_draft(ctx)
        with self.assertRaises(Exception):
            compat.generate(ctx)

    def test_compat_declares_source_publication(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        written = compat.generate(ctx)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        for rel in written:
            if rel.startswith("legacy/"):
                continue
            envelope = json.loads((view_root / rel).read_text(encoding="utf-8"))
            self.assertEqual(envelope["sourcePublicationId"], "pub_a")
            self.assertEqual(schemas.validate_compatibility_view(envelope), [])


if __name__ == "__main__":
    unittest.main()
