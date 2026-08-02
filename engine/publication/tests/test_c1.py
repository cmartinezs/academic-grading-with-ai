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
from copy import deepcopy
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
    PublicationError,
    ReviewHashMismatchError,
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


# ---------------------------------------------------------------------------
# multiprocess concurrency workers (must be module-level for pickling)
# ---------------------------------------------------------------------------


def _mp_dispatch(kind: str, base: str, section: str, pub: str, env: dict, review_hash: str | None):
    from publication import builder
    from publication.clock import Clock

    ctx = builder.BuildContext.resolve(
        base, section, publication_id=pub, env=env, clock=Clock(env=env),
        legacy_source=str(Path(base) / "legacy"),
    )
    try:
        if kind == "build":
            builder.build_draft(ctx)
        elif kind == "review":
            builder.review_draft(ctx, review_hash, "reviewer-a")
        elif kind == "approve":
            builder.approve_draft(ctx, review_hash, "approver-a", "approve")
        elif kind == "discard":
            builder.discard_staging(ctx)
        else:
            raise ValueError(f"unknown kind: {kind}")
        return ("ok", None)
    except Exception as exc:  # noqa: BLE001
        return (type(exc).__name__, str(exc))


def _run_workers(jobs) -> list:
    import multiprocessing

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(len(jobs)) as pool:
        return pool.starmap(_mp_dispatch, jobs)


def _mp_dispatch_compat(kind: str, base: str, section: str, pub: str, env: dict):
    """Worker for compat operations on an already-approved snapshot (picklable)."""
    import json

    from publication import builder, compat
    from publication.clock import Clock

    ctx = builder.BuildContext.resolve(
        base, section, publication_id=pub, env=env, clock=Clock(env=env),
        legacy_source=str(Path(base) / "legacy"),
    )
    try:
        if kind == "compat_generate":
            return ("ok", compat.generate(ctx, update_legacy_aliases=True))
        elif kind == "compat_generate_replace":
            return ("ok", compat.generate(ctx, update_legacy_aliases=True, replace_legacy_aliases=True))
        elif kind == "compat_revoke":
            builder.transition(ctx, "revoked", actor="ops", reason="concurrent")
            return ("ok", None)
        elif kind == "compat_corrected":
            sections = ctx.sections_root() / section
            by_pub = None
            if sections.is_dir():
                for d in sorted(p for p in sections.iterdir() if p.is_dir()):
                    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
                    if manifest.get("correctsPublicationId") == pub:
                        by_pub = d.name
                        break
            if by_pub is None:
                return ("PublicationError", "no correcting publication for the race")
            builder.transition(
                ctx, "corrected", actor="ops", by_publication_id=by_pub,
                validate_reference=lambda _by, _et: None,
            )
            return ("ok", None)
        else:
            raise ValueError(f"unknown kind: {kind}")
    except Exception as exc:  # noqa: BLE001
        return (type(exc).__name__, str(exc))


def _run_workers_compat(jobs) -> list:
    import multiprocessing

    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(len(jobs)) as pool:
        return pool.starmap(_mp_dispatch_compat, jobs)


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
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        dest = builder.approve_draft(ctx, result.review_hash, "approver-a", "approve", content_hash=result.content_hash)
        return ctx, result.content_hash, dest

    def reviewed_flow(self, pub: str = "pub_a", section: str = SECTION, ruts=(RUT_A, RUT_B), **kwargs):
        ctx = self.prep(pub, section=section, ruts=ruts)
        result = builder.build_draft(ctx, **kwargs)
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        return ctx, result.review_hash, result.content_hash

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
# P0 hashes: artifact/content/review layers, dry-run parity, volatile-stripping
# ---------------------------------------------------------------------------


class HashSchemeTest(C1TestCase):
    def test_dry_run_parity_with_build(self):
        """Dry-run content/review hashes must match a real build (P0 item 1)."""
        self.ensure_identity((RUT_A, RUT_B))
        ctx = self.ctx("pub_parity")
        dry = builder.build_draft(ctx, dry_run=True)
        built = builder.build_draft(ctx)
        self.assertEqual(dry.content_hash, built.content_hash)
        self.assertEqual(dry.review_hash, built.review_hash)

    def test_content_hash_strips_legacy_generated_at(self):
        """Different legacy generatedAt values must not change contentHash (P0 item 7)."""
        from publication.legacy import COURSE_FILE, MANIFEST_FILE

        self.ensure_identity((RUT_A, RUT_B))

        def build_with_generated_at(ts: str):
            course_payload = json.loads((self.legacy / "course" / COURSE_FILE).read_text(encoding="utf-8"))
            course_payload["generatedAt"] = ts
            write(self.legacy / "course" / COURSE_FILE, course_payload)
            manifest_payload = json.loads((self.legacy / MANIFEST_FILE).read_text(encoding="utf-8"))
            manifest_payload["generatedAt"] = ts
            write(self.legacy / MANIFEST_FILE, manifest_payload)
            result = builder.build_draft(self.ctx(), dry_run=True)
            return result.content_hash, result.review_hash

        h1 = build_with_generated_at("2026-01-01T10:00:00")
        h2 = build_with_generated_at("2026-06-01T22:30:00")
        self.assertEqual(h1, h2)

    def test_review_hash_covers_manifest_core_and_classification(self):
        """Tampering engineVersion or classification must break reviewHash (P0 items 4, 8)."""
        self.ensure_identity((RUT_A, RUT_B))
        ctx = self.ctx()
        result = builder.build_draft(ctx)
        manifest = json.loads((ctx.staging_dir() / "manifest.json").read_text(encoding="utf-8"))
        manifest["engineVersion"] = "tampered"
        write(ctx.staging_dir() / "manifest.json", manifest)
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G7-manifest"))

    def test_approval_cross_validates_manifest_review_approval(self):
        """review.json contentHash tampering must fail verification (P0 item 8)."""
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        review_path = ctx.staging_dir() / "approvals/review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["contentHash"] = "f" * 64
        write(review_path, review)
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G8-lifecycle"))

    def test_engine_provenance_has_no_built_at(self):
        """builtAt belongs to the manifest; engine provenance is logical (P0 item 5)."""
        ctx = self.prep()
        builder.build_draft(ctx)
        engine = json.loads(
            (ctx.staging_dir() / "provenance/engine.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("builtAt", engine)
        manifest = json.loads((ctx.staging_dir() / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("builtAt", manifest)
        self.assertRegex(manifest["builtAt"], r"^\d{4}-\d{2}-\d{2}T")


# ---------------------------------------------------------------------------
# P0 privacy: absolute paths, roster names, classification
# ---------------------------------------------------------------------------


class PrivacyP0Test(C1TestCase):
    def test_absolute_paths_blocked(self):
        """POSIX, Windows and file:// absolute references must fail G6 (P0 item 25)."""
        results = deepcopy(DEFAULT_RESULTS)
        results[0]["finalFeedback"] = "see /etc/passwd for details"
        self.write_legacy(results=results)
        ctx = self.prep()
        with self.assertRaises(GateError) as caught:
            builder.build_draft(ctx)
        self.assertIn("Absolute path", " ".join(caught.exception.details))

    def test_windows_absolute_path_blocked(self):
        results = deepcopy(DEFAULT_RESULTS)
        results[0]["finalFeedback"] = "log at C:\\Users\\me\\out.txt"
        self.write_legacy(results=results)
        ctx = self.prep()
        with self.assertRaises(GateError):
            builder.build_draft(ctx)

    def test_file_url_blocked(self):
        results = deepcopy(DEFAULT_RESULTS)
        results[0]["finalFeedback"] = "evidence at file:///mnt/data/results"
        self.write_legacy(results=results)
        ctx = self.prep()
        with self.assertRaises(GateError):
            builder.build_draft(ctx)

    def test_roster_name_in_feedback_blocked(self):
        """Known roster names in free text must fail the gate (P0 items 26-27)."""
        results = deepcopy(DEFAULT_RESULTS)
        results[0]["finalFeedback"] = "Buen trabajo Ana Soto"
        self.write_legacy(results=results)
        ctx = self.prep()
        with self.assertRaises(GateError) as caught:
            builder.build_draft(ctx)
        self.assertIn("roster name", " ".join(caught.exception.details).lower())

    def test_classification_mismatch_detected(self):
        """Wrong classification/audience for a rel path must fail G9 (P0 item 31)."""
        ctx = self.prep()
        builder.build_draft(ctx)
        manifest = json.loads((ctx.staging_dir() / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["canonical/subjects.json"]["classification"] = "INTERNAL"
        write(ctx.staging_dir() / "manifest.json", manifest)
        report = builder.verify(ctx, "staging")
        self.assertFalse(report.passed())
        self.assertTrue(report.gate_findings("G9-classification"))

    def test_no_invented_evidence_refs(self):
        """Results must not carry invented evidence references (P0 item 34)."""
        ctx = self.prep()
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        for result in canonical["canonical/results.json"]["results"]:
            self.assertEqual(result["evidenceRefs"], [])

    def test_form_and_term_preserved(self):
        """Per-result form and section term must be preserved (P0 item 33)."""
        course = json.loads((self.legacy / "course/course.json").read_text(encoding="utf-8"))
        course["course"]["term"] = "2026-1"
        write(self.legacy / "course/course.json", course)
        ctx = self.prep()
        _, canonical, _ = builder.compute_plan_payloads(ctx)
        self.assertEqual(canonical["canonical/section.json"]["term"], "2026-1")
        forms = {r["form"] for r in canonical["canonical/results.json"]["results"]}
        self.assertEqual(forms, {"A", "B"})


# ---------------------------------------------------------------------------
# P0 hash review binding end-to-end
# ---------------------------------------------------------------------------


class HashBindingTest(C1TestCase):
    def test_tampered_manifest_core_blocks_approval(self):
        """Manifest engine-version tampering must block approval (P0 item 8)."""
        ctx = self.prep()
        result = builder.build_draft(ctx)
        manifest = json.loads((ctx.staging_dir() / "manifest.json").read_text(encoding="utf-8"))
        manifest["engineVersion"] = "tampered"
        write(ctx.staging_dir() / "manifest.json", manifest)
        with self.assertRaises(ReviewHashMismatchError):
            builder.review_draft(ctx, result.review_hash, "reviewer-a")


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
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        with mock.patch.object(builder.os, "rename", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                builder.approve_draft(ctx, result.review_hash, "approver-a", "approve")
        self.assertFalse(ctx.destination_dir().exists())
        self.assertTrue(ctx.staging_dir().is_dir())

    def test_existing_destination_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        ctx.destination_dir().mkdir(parents=True, exist_ok=True)
        with self.assertRaises(DestinationExistsError):
            builder.approve_draft(ctx, result.review_hash, "approver-a", "approve")

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
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        self.assertTrue((ctx.staging_dir() / "approvals/review.json").is_file())

    def test_review_wrong_review_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        wrong = "0" * 64
        with self.assertRaises(ReviewHashMismatchError):
            builder.review_draft(ctx, wrong, "reviewer-a")

    def test_review_wrong_content_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        with self.assertRaises(ContentHashMismatchError):
            builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash="f" * 64)

    def test_change_after_review_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        (ctx.staging_dir() / "canonical/results.json").write_text('{"results": []}\n', encoding="utf-8")
        with self.assertRaises(ReviewHashMismatchError):
            builder.approve_draft(ctx, result.review_hash, "approver-a", "approve")

    def test_approve_without_review(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        with self.assertRaises(NotReviewedError):
            builder.approve_draft(ctx, result.review_hash, "approver-a", "approve")

    def test_approval_requires_confirmation(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        with self.assertRaises(ConfirmationRequiredError):
            builder.approve_draft(ctx, result.review_hash, "approver-a", "")

    def test_approve_wrong_review_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        with self.assertRaises(ReviewHashMismatchError):
            builder.approve_draft(ctx, "f" * 64, "approver-a", "approve")

    def test_approve_wrong_content_hash_rejected(self):
        ctx = self.prep()
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a")
        with self.assertRaises(ContentHashMismatchError):
            builder.approve_draft(ctx, result.review_hash, "approver-a", "approve", content_hash="f" * 64)


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

        def validate_reference(by_pub: str, event_type: str) -> None:
            dest = ctx_b.sections_root() / SECTION / by_pub
            self.assertTrue(builder.approved_snapshot_exists(ctx_b, by_pub))
            self.assertTrue(builder.is_approved_snapshot(ctx_b, by_pub))
            manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("correctsPublicationId"), "pub_a")

        ledger.append(
            "corrected",
            "pub_a",
            actor="ops",
            by_publication_id="pub_b",
            validate_reference=validate_reference,
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
        self.assertEqual(ledger.current_state("pub_a"), "approved")
        ledger.append(
            "superseded",
            "pub_a",
            actor="ops",
            by_publication_id="pub_b",
            validate_reference=lambda _by, _et: None,
        )
        self.assertEqual(ledger.current_state("pub_a"), "superseded")

    def test_correction_reference_must_be_approved(self):
        self.approve_flow("pub_a")
        ctx = self.prep("pub_c")
        with self.assertRaises(GateError):
            builder.build_draft(ctx, corrects_publication_id="pub_ghost")


# ---------------------------------------------------------------------------
# P0 lifecycle: lock-before-read, states, actor rules, lineage validation
# ---------------------------------------------------------------------------


class LifecycleP0Test(C1TestCase):
    def _ledger(self):
        return LifecycleLedger(self.roots / "state", SECTION, clock=Clock(env=self.env))

    def test_nonexistent_distinct_from_created(self):
        ledger = self._ledger()
        self.assertEqual(ledger.current_state("pub_ghost"), "nonexistent")
        ledger.append("created", "pub_ghost", actor="system")
        self.assertEqual(ledger.current_state("pub_ghost"), "created")

    def test_duplicate_created_rejected(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("created", "pub_a", actor="system")

    def test_corrupt_seq_rejected_before_append(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        ledger.append("reviewed", "pub_a", actor="reviewer-a")
        events = ledger.read_events()
        events[1]["seq"] = 9
        ledger.path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(LedgerError):
            ledger.append("approved", "pub_a", actor="approver-a")

    def test_actor_required(self):
        ledger = self._ledger()
        with self.assertRaises(InvalidTransitionError):
            ledger.append("created", "pub_a", actor=None)

    def test_actor_must_be_non_email_and_sanitized(self):
        ledger = self._ledger()
        with self.assertRaises(InvalidTransitionError):
            ledger.append("created", "pub_a", actor="ops@mail.cl")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("created", "pub_a", actor="../evil\nactor")

    def test_self_reference_rejected(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        ledger.append("reviewed", "pub_a", actor="reviewer-a")
        ledger.append("approved", "pub_a", actor="approver-a")
        with self.assertRaises(InvalidTransitionError):
            ledger.append(
                "superseded", "pub_a", actor="ops",
                by_publication_id="pub_a",
                validate_reference=lambda _by, _et: None,
            )

    def test_reference_validation_mandatory(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        ledger.append("reviewed", "pub_a", actor="reviewer-a")
        ledger.append("approved", "pub_a", actor="approver-a")
        with self.assertRaises(InvalidTransitionError):
            ledger.append("superseded", "pub_a", actor="ops", by_publication_id="pub_b")

    def test_reference_validation_failure_propagates(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        ledger.append("reviewed", "pub_a", actor="reviewer-a")
        ledger.append("approved", "pub_a", actor="approver-a")

        def reject(_by, _et):
            raise InvalidTransitionError("referenced publication is not approved")

        with self.assertRaises(InvalidTransitionError):
            ledger.append("superseded", "pub_a", actor="ops", by_publication_id="pub_b", validate_reference=reject)

    def test_manifest_lineage_must_match_transition(self):
        """A transition cannot reference an approved pub whose manifest does not declare the lineage."""
        ctx_a, _, _ = self.approve_flow("pub_a")
        ctx_b, _, _ = self.approve_flow("pub_b")  # does NOT declare supersedes pub_a
        ledger = ctx_a.ledger()

        def validate_reference(by_pub, event_type):
            dest = ctx_a.sections_root() / SECTION / by_pub
            manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("supersedesPublicationId") != "pub_a":
                raise InvalidTransitionError(
                    f"{by_pub} does not declare supersedesPublicationId=pub_a"
                )

        with self.assertRaises(InvalidTransitionError):
            ledger.append(
                "superseded", "pub_a", actor="ops",
                by_publication_id="pub_b",
                validate_reference=validate_reference,
            )

    def test_published_is_receipt_not_state(self):
        ledger = self._ledger()
        ledger.append("created", "pub_a", actor="system")
        ledger.append("reviewed", "pub_a", actor="reviewer-a")
        ledger.append("approved", "pub_a", actor="approver-a")
        ledger.append("published", "pub_a", actor="ops", receipt="rcpt-1")
        self.assertEqual(ledger.current_state("pub_a"), "approved")
        self.assertTrue(ledger.has_approved("pub_a"))
        receipts = [e for e in ledger.read_events() if e["event"] == "published"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["receipt"], "rcpt-1")

    def test_concurrent_appends_same_publication(self):
        ledger = self._ledger()
        ledger.append("created", "pub_x", actor="system")
        ledger.append("reviewed", "pub_x", actor="reviewer-a")
        ledger.append("approved", "pub_x", actor="approver-a")
        errors: list[Exception] = []

        def publish():
            try:
                ledger.append("published", "pub_x", actor="ops", receipt="r-x")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=publish) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        events = ledger.read_events()
        seqs = [int(event["seq"]) for event in events]
        self.assertEqual(len(seqs), len(set(seqs)), "seqs must be unique under concurrency")
        self.assertEqual(max(seqs), len(events))


# ---------------------------------------------------------------------------
# P0 concurrency: per-publication lock serializes mutations (P0 items 10-14)
# ---------------------------------------------------------------------------


class ConcurrencyTest(C1TestCase):
    def _job(self, kind: str, pub: str, review_hash: str | None = None) -> tuple:
        return (
            kind,
            str(self.base),
            SECTION,
            pub,
            {**self.env},
            review_hash,
        )

    def _assert_no_partial_destination(self, ctx, pub: str) -> None:
        """The destination is either fully present and verified, or absent."""
        dest = ctx.sections_root() / SECTION / pub
        if dest.exists():
            report = builder.verify(ctx, "approved")
            self.assertTrue(report.passed(), [f.message for f in report.findings])

    def test_concurrent_builds_same_publication(self):
        self.ensure_identity((RUT_A, RUT_B))
        pub = "pub_conc"
        results = _run_workers(
            [self._job("build", pub), self._job("build", pub)]
        )
        kinds = [kind for kind, _ in results]
        self.assertEqual(sorted(kinds), ["StagingExistsError", "ok"])
        ctx = self.ctx(pub)
        report = builder.verify(ctx, "staging")
        self.assertTrue(report.passed(), [f.message for f in report.findings])

    def test_concurrent_approve_approve(self):
        self.ensure_identity((RUT_A, RUT_B))
        ctx_b = self.prep("pub_conc2")
        result = builder.build_draft(ctx_b)
        builder.review_draft(ctx_b, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        results = _run_workers(
            [self._job("approve", "pub_conc2", result.review_hash), self._job("approve", "pub_conc2", result.review_hash)]
        )
        kinds = sorted(kind for kind, _ in results)
        self.assertIn("ok", kinds)
        self.assertEqual(len([k for k in kinds if k == "ok"]), 1)
        self._assert_no_partial_destination(ctx_b, "pub_conc2")
        ledger = ctx_b.ledger()
        approved_events = [e for e in ledger.read_events() if e["event"] == "approved" and e["publicationId"] == "pub_conc2"]
        self.assertEqual(len(approved_events), 1, "double approval must be impossible")

    def test_concurrent_review_approve(self):
        self.ensure_identity((RUT_A, RUT_B))
        ctx = self.ctx("pub_conc3")
        result = builder.build_draft(ctx)
        results = _run_workers(
            [self._job("review", "pub_conc3", result.review_hash), self._job("approve", "pub_conc3", result.review_hash)]
        )
        dest = ctx.sections_root() / SECTION / "pub_conc3"
        staging = ctx.staging_dir()
        if dest.exists():
            self.assertTrue(builder.verify(ctx, "approved").passed())
            self.assertFalse(staging.exists())
        else:
            self.assertTrue(staging.is_dir())
            self.assertTrue(builder.verify(ctx, "staging").passed())

    def test_concurrent_discard_approve(self):
        self.ensure_identity((RUT_A, RUT_B))
        ctx = self.ctx("pub_conc4")
        result = builder.build_draft(ctx)
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        results = _run_workers(
            [self._job("discard", "pub_conc4"), self._job("approve", "pub_conc4", result.review_hash)]
        )
        dest = ctx.sections_root() / SECTION / "pub_conc4"
        staging = ctx.staging_dir()
        if dest.exists():
            self.assertTrue(builder.verify(ctx, "approved").passed())
            self.assertFalse(staging.exists())
        else:
            self.assertFalse(staging.exists(), "staging must not be left behind after discard/approve race")


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
        self.assertIn("legacy/course/results.json", written)
        self.assertIn("legacy/PROVENANCE.json", written)
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


# ---------------------------------------------------------------------------
# P0 compatibility: verified source, revoked block, atomic staging, aliases
# ---------------------------------------------------------------------------


class CompatP0Test(C1TestCase):
    def test_blocks_revoked_snapshot(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        ctx.ledger().append("revoked", "pub_a", actor="ops", reason="irregular")
        with self.assertRaises(PublicationError):
            compat.generate(ctx)

    def test_blocks_superseded_snapshot(self):
        ctx_a, _, _ = self.approve_flow("pub_a")
        ctx_b, _, _ = self.approve_flow(
            "pub_b", **{"supersedes_publication_id": "pub_a"}
        )
        ledger = ctx_b.ledger()
        ledger.append(
            "superseded", "pub_a", actor="ops", by_publication_id="pub_b",
            validate_reference=lambda _by, _et: None,
        )
        with self.assertRaises(PublicationError):
            compat.generate(ctx_a)

    def test_rejects_overwrite(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx)
        with self.assertRaises(DestinationExistsError):
            compat.generate(ctx)

    def test_zero_files_when_snapshot_tampered(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        path = dest / "canonical/results.json"
        os.chmod(path, 0o600)
        path.write_text('{"results": []}\n', encoding="utf-8")
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        with self.assertRaises(PublicationError):
            compat.generate(ctx)
        self.assertFalse(view_root.exists(), "no partial views on failure")

    def test_aliases_are_exact_content_with_provenance_sidecar(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        results_alias = json.loads(
            (alias_root / "course/results.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("content", results_alias, "alias must be bare content")
        self.assertNotIn("sourcePublicationId", results_alias)
        self.assertIn("items", results_alias, "legacy consumers read an 'items' wrapper")
        for row in results_alias["items"]:
            self.assertIsNone(row["resultPath"], "private evidence paths are never reproduced")
            self.assertNotEqual(row["studentId"], RUT_A, "opaque ids only, never RUTs")
            for key in compat.LEGACY_RESULT_KEYS:
                self.assertIn(key, row)
        provenance = json.loads(
            (alias_root / "PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provenance["sourcePublicationId"], "pub_a")
        self.assertEqual(provenance["canonicalSourceHash"], content_hash)

    def test_consumer_views_match_canonical(self):
        """A legacy-style consumer reads aliases and sees canonical semantics."""
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        aliased = json.loads(
            (alias_root / "course/results.json").read_text(encoding="utf-8")
        )
        canonical = json.loads(
            (dest / "canonical/results.json").read_text(encoding="utf-8")
        )["results"]
        by_key = {(r["studentId"], r["assessmentId"], r["form"]): r for r in canonical}
        self.assertEqual(len(aliased["items"]), len(canonical))
        for row in aliased["items"]:
            source = by_key[(row["studentId"], row["evaluationId"], row["form"])]
            self.assertEqual(row["score"], source["score"])
            self.assertEqual(row["grade"], source["grade"])
            self.assertEqual(row["status"], source["status"])
            self.assertEqual(row["studentId"], source["studentId"])
            self.assertEqual(row["ies"], source["components"])

    def test_real_legacy_consumer_processes_alias_unmodified(self):
        """The real consumer (sync-section-indexes.py) reads the alias exactly as the
        published export and produces evaluations/<SECTION>/grades.json with no changes."""
        import importlib.util
        import sys

        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)

        workspace = self.base / "consumer-ws"
        section_dir = workspace / "evaluations" / SECTION
        export_course = workspace / "exports" / "publication-input" / "course"
        section_dir.mkdir(parents=True)
        export_course.mkdir(parents=True)
        write(
            section_dir / "config.json",
            {"course": {"name": SECTION}, "defaults": {}, "access": {}, "evaluations": {}},
        )
        write(section_dir / "students.json", {"students": []})
        results_alias = json.loads(
            (alias_root / "course/results.json").read_text(encoding="utf-8")
        )
        write(export_course / "results.json", results_alias)

        script = Path(__file__).resolve().parents[3] / "engine" / "scripts" / "sync-section-indexes.py"
        spec = importlib.util.spec_from_file_location("legacy_consumer_under_test", script)
        consumer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consumer)
        consumer.ROOT = workspace

        old_argv = list(sys.argv)
        sys.argv = ["sync-section-indexes.py", "--section", SECTION]
        try:
            consumer.main()
        finally:
            sys.argv = old_argv

        grades = json.loads((section_dir / "grades.json").read_text(encoding="utf-8"))["grades"]
        canonical = json.loads(
            (dest / "canonical/results.json").read_text(encoding="utf-8")
        )["results"]
        by_key = {(r["studentId"], r["assessmentId"], r["form"]): r for r in canonical}
        self.assertEqual(len(grades), len(canonical), "same cardinality through the real consumer")
        for row in grades:
            source = by_key[(row["studentId"], row["evaluationId"], row["form"])]
            self.assertEqual(row["form"], source["form"])
            self.assertEqual(row["status"], source["status"])
            self.assertEqual(row["score"], source["score"])
            self.assertEqual(row["grade"], source["grade"])
            self.assertEqual(row["finalFeedback"], source["feedback"])
            self.assertEqual(row["ies"], source["components"])
            self.assertIsNone(row["resultPath"], "private evidence path is never reproduced")


# ---------------------------------------------------------------------------
# Final compat: concurrency, crash-before/after-rename, privacy zero-files
# ---------------------------------------------------------------------------


class CompatFinalTest(C1TestCase):
    def _assert_views_complete(self, view_root, content_hash):
        for envelope_path in sorted(view_root.rglob("*.json")):
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["sourcePublicationId"], "pub_a")
            self.assertEqual(envelope["canonicalSourceHash"], content_hash)
            self.assertEqual(schemas.validate_compatibility_view(envelope), [])
            self.assertIn("content", envelope)

    def test_simultaneous_generates_single_winner(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        jobs = [("compat_generate", str(self.base), SECTION, "pub_a", self.env) for _ in range(2)]
        results = _run_workers_compat(jobs)
        kinds = sorted(r[0] for r in results)
        self.assertEqual(kinds, ["DestinationExistsError", "ok"], results)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        self.assertTrue(view_root.is_dir())
        self._assert_views_complete(view_root, content_hash)
        staging = ctx.runtime.temp_root / "compat-staging" / SECTION / "pub_a"
        self.assertFalse(staging.exists() and any(staging.iterdir()), "no staging leftovers")

    def test_generate_vs_terminal_transition_serialize(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        results = _run_workers_compat([
            ("compat_revoke", str(self.base), SECTION, "pub_a", self.env),
            ("compat_generate", str(self.base), SECTION, "pub_a", self.env),
        ])
        outcomes = {r[0] for r in results}
        self.assertLessEqual(outcomes, {"ok", "PublicationError"}, results)
        if "ok" in outcomes:
            view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
            if view_root.is_dir():
                self._assert_views_complete(view_root, content_hash)

    def test_crash_before_rename_leaves_no_destination(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        with mock.patch.object(compat, "_fsync_tree", side_effect=RuntimeError("crash before rename")):
            with self.assertRaises(RuntimeError):
                compat.generate(ctx)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        self.assertFalse(view_root.exists(), "no views on crash before rename")
        staging = ctx.runtime.temp_root / "compat-staging" / SECTION / "pub_a"
        self.assertFalse(staging.exists() and any(staging.iterdir()), "own staging cleaned")

    def test_crash_after_rename_leaves_complete_views(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        with mock.patch.object(compat, "_fsync_parent", side_effect=RuntimeError("crash after rename")):
            with self.assertRaises(RuntimeError):
                compat.generate(ctx)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        self.assertTrue(view_root.is_dir(), "views promoted before the crash")
        self._assert_views_complete(view_root, content_hash)
        self.assertFalse(
            [f for f in (ctx.runtime.temp_root / "compat-staging").rglob("*") if f.is_file()],
            "no leftover staging files",
        )

    def test_privacy_failure_leaves_zero_destination_files(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")

        def leaking_gate(report, root, files, known_names=None):
            report.add("G6-privacy", "BLOCK pii-email: email address in feedback")

        with mock.patch.object(compat, "gate_privacy", side_effect=leaking_gate):
            with self.assertRaises(PublicationError):
                compat.generate(ctx)
        view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
        self.assertFalse(view_root.exists(), "zero destination files on privacy failure")


# ---------------------------------------------------------------------------
# Final aliases: atomic bundle failure injection
# ---------------------------------------------------------------------------


class AliasAtomicTest(C1TestCase):
    def _alias_files(self, ctx):
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        if not alias_root.is_dir():
            return {}
        return {
            path.relative_to(alias_root).as_posix(): json.loads(path.read_text(encoding="utf-8"))
            for path in alias_root.rglob("*.json")
        }

    def _canonical_and_manifest(self, dest):
        canonical = {
            "section": json.loads((dest / "canonical/section.json").read_text(encoding="utf-8")),
            "subjects": json.loads((dest / "canonical/subjects.json").read_text(encoding="utf-8")),
            "assessments": json.loads((dest / "canonical/assessments.json").read_text(encoding="utf-8")),
            "results": json.loads((dest / "canonical/results.json").read_text(encoding="utf-8")),
            "policy": json.loads((dest / "canonical/policy.json").read_text(encoding="utf-8")),
        }
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        return canonical, manifest

    def _assert_no_alias_staging_files(self, ctx):
        self.assertFalse(
            [f for f in (ctx.runtime.temp_root / "compat-alias-staging").rglob("*") if f.is_file()],
            "no leftover alias staging files",
        )

    def test_crash_writing_second_alias_file(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        alias_writes = {"count": 0}
        real_write = compat.write_json

        def flaky_write(path, payload):
            if "compat-alias-staging" in str(path):
                alias_writes["count"] += 1
                if alias_writes["count"] == 2:
                    raise RuntimeError("crash writing second alias file")
            return real_write(path, payload)

        with mock.patch.object(compat, "write_json", side_effect=flaky_write):
            with self.assertRaises(RuntimeError):
                compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        self.assertFalse(alias_root.exists(), "no partial alias bundle on crash")
        self._assert_no_alias_staging_files(ctx)

    def test_crash_before_alias_rename(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        real_fsync = compat._fsync_tree

        def flaky_fsync(root):
            if "compat-alias-staging" in str(root):
                raise RuntimeError("crash before alias rename")
            return real_fsync(root)

        with mock.patch.object(compat, "_fsync_tree", side_effect=flaky_fsync):
            with self.assertRaises(RuntimeError):
                compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        self.assertFalse(alias_root.exists(), "no alias bundle on crash before rename")

    def test_crash_after_backup_move_restores_old_bundle(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        before = self._alias_files(ctx)
        self.assertTrue(before)
        canonical, manifest = self._canonical_and_manifest(dest)

        rename_calls = {"count": 0}
        real_rename = os.rename

        def flaky_rename(src, dst):
            rename_calls["count"] += 1
            if rename_calls["count"] == 2:
                raise RuntimeError("crash after backup move, before promote")
            return real_rename(src, dst)

        with mock.patch.object(compat.os, "rename", side_effect=flaky_rename):
            with self.assertRaises(RuntimeError):
                compat._commit_legacy_aliases_locked(ctx, canonical, manifest, replace_existing=True)
        self.assertTrue(alias_root.is_dir(), "old bundle restored on failure")
        self.assertEqual(self._alias_files(ctx), before, "restored bundle is byte-identical")

    def test_crash_after_promote_keeps_new_bundle(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx, update_legacy_aliases=True)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        canonical, manifest = self._canonical_and_manifest(dest)

        fsync_calls = {"count": 0}
        real_fsync_parent = compat._fsync_parent

        def flaky_fsync_parent(path):
            fsync_calls["count"] += 1
            if fsync_calls["count"] == 1:
                raise RuntimeError("crash after alias promote")
            return real_fsync_parent(path)

        with mock.patch.object(compat, "_fsync_parent", side_effect=flaky_fsync_parent):
            with self.assertRaises(RuntimeError):
                compat._commit_legacy_aliases_locked(ctx, canonical, manifest, replace_existing=True)
        self.assertTrue(alias_root.is_dir(), "new bundle promoted before the crash")
        results = json.loads((alias_root / "course/results.json").read_text(encoding="utf-8"))
        self.assertIn("items", results, "promoted bundle is the complete new bundle")

    def test_two_concurrent_updates_serialize_without_corruption(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        jobs = [
            ("compat_generate_replace", str(self.base), SECTION, "pub_a", self.env) for _ in range(2)
        ]
        results = _run_workers_compat(jobs)
        self.assertEqual(sorted(r[0] for r in results), ["DestinationExistsError", "ok"], results)
        alias_root = compat.legacy_alias_dir(ctx, SECTION)
        results_json = json.loads((alias_root / "course/results.json").read_text(encoding="utf-8"))
        self.assertIn("items", results_json)
        self._assert_no_alias_staging_files(ctx)
        backup = ctx.runtime.temp_root / "compat-alias-backup" / SECTION / "pub_a"
        self.assertFalse([f for f in backup.rglob("*") if f.is_file()], "backup cleaned after success")


# ---------------------------------------------------------------------------
# P0 recovery: crash states, idempotent reconciliation, never-delete
# ---------------------------------------------------------------------------


class RecoveryP0Test(C1TestCase):
    def test_crash_after_rename_before_chmod(self):
        ctx, review_hash, content_hash = self.reviewed_flow("pub_a")
        dest = ctx.destination_dir()
        with mock.patch.object(builder, "_make_read_only", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                builder.approve_draft(ctx, review_hash, "approver-a", "approve", content_hash=content_hash)
        self.assertTrue(dest.exists(), "snapshot promoted before the crash")
        self.assertTrue(builder._writable_files(dest), "files left writable")
        self.assertNotEqual(ctx.ledger().current_state("pub_a"), "approved")

        actions = builder.reconcile(ctx)
        self.assertTrue(any("readonly-restored" in a for a in actions), actions)
        self.assertTrue(any("ledger-reconciled" in a for a in actions), actions)
        self.assertFalse(builder._writable_files(dest))
        self.assertEqual(ctx.ledger().current_state("pub_a"), "approved")

    def test_crash_after_chmod_before_approved_append(self):
        ctx, review_hash, content_hash = self.reviewed_flow("pub_a")
        dest = ctx.destination_dir()
        real_append = LifecycleLedger.append

        def crash_on_approved(self, event_type, publication_id, **kwargs):
            if event_type == "approved":
                raise RuntimeError("crash before ledger append")
            return real_append(self, event_type, publication_id, **kwargs)

        with mock.patch.object(LifecycleLedger, "append", crash_on_approved):
            with self.assertRaises(RuntimeError):
                builder.approve_draft(ctx, review_hash, "approver-a", "approve", content_hash=content_hash)
        self.assertTrue(dest.exists())
        self.assertFalse(builder._writable_files(dest))
        self.assertEqual(ctx.ledger().current_state("pub_a"), "reviewed")

        actions = builder.reconcile(ctx)
        self.assertTrue(any("ledger-reconciled" in a for a in actions), actions)
        self.assertEqual(ctx.ledger().current_state("pub_a"), "approved")

    def test_reconcile_is_idempotent(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        first = builder.reconcile(ctx)
        second = builder.reconcile(ctx)
        self.assertEqual(first, [])
        self.assertEqual(second, [])

    def test_reconcile_never_deletes_promoted_snapshot(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        ledger = ctx.ledger()
        ledger.append("revoked", "pub_a", actor="ops", reason="irregular")
        before = set(p.name for p in dest.parent.iterdir())
        actions = builder.reconcile(ctx)
        after = set(p.name for p in dest.parent.iterdir())
        self.assertTrue(dest.exists(), "promoted snapshot must survive revocation")
        self.assertEqual(before, after)
        self.assertTrue(all(not a.startswith("deleted") for a in actions), actions)

    def test_reconcile_reports_integrity_failure_without_deleting(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        path = dest / "canonical/results.json"
        os.chmod(path, 0o600)
        path.write_text('{"results": []}\n', encoding="utf-8")
        actions = builder.reconcile(ctx)
        self.assertTrue(any("integrity-failed:pub_a" in a for a in actions), actions)
        self.assertTrue(dest.exists(), "integrity failure must not delete the snapshot")


# ---------------------------------------------------------------------------
# Final: exceptions never leak RUT/email/absolute paths (source-level)
# ---------------------------------------------------------------------------


class ExceptionPrivacyTest(C1TestCase):
    EMAIL = "estudiante@ejemplo.cl"

    def _leak_strings(self):
        return [
            self.env["ACADGRAD_PRIVATE_ROOT"],
            self.env["ACADGRAD_STATE_ROOT"],
            self.env["ACADGRAD_PUBLICATIONS_ROOT"],
            self.env["ACADGRAD_TEMP_ROOT"],
            str(self.base),
            str(self.legacy),
            RUT_A,
            self.EMAIL,
            os.path.expanduser("~"),
        ]

    def _assert_clean(self, exc) -> None:
        text = str(exc)
        for leak in self._leak_strings():
            self.assertNotIn(leak, text, f"exception leaks {leak!r}")

    def test_privacy_gate_finding_does_not_leak_absolute_path(self):
        """G6 findings surface in GateError.details and must never embed the value."""
        results = deepcopy(DEFAULT_RESULTS)
        results[0]["finalFeedback"] = f"see {self.base}/leaked/absolute/path for details"
        self.write_legacy(results=results)
        ctx = self.prep()
        with self.assertRaises(GateError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)
        for detail in cm.exception.details:
            for leak in self._leak_strings():
                self.assertNotIn(leak, detail, f"finding detail leaks {leak!r}")

    def test_unmapped_student_exception_clean(self):
        self.ensure_identity([RUT_A])
        ctx = self.ctx()
        with self.assertRaises(UnmappedStudentError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)
        self.assertNotIn(RUT_B, str(cm.exception), "unmapped id must not be reproduced")

    def test_missing_legacy_export_exception_clean(self):
        ctx = self.ctx(legacy_source=str(self.base / "empty"))
        with self.assertRaises(MissingLegacyExportError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)

    def test_course_mismatch_exception_clean(self):
        ctx = self.ctx(section="OTRA-SECCION")
        with self.assertRaises(LegacyCourseMismatchError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)

    def test_staging_exists_exception_clean(self):
        ctx = self.prep()
        builder.build_draft(ctx)
        with self.assertRaises(StagingExistsError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)

    def test_immutable_snapshot_exception_clean(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        with self.assertRaises(ImmutableSnapshotError) as cm:
            builder.build_draft(ctx)
        self._assert_clean(cm.exception)

    def test_destination_exists_exception_clean(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        compat.generate(ctx)
        with self.assertRaises(DestinationExistsError) as cm:
            compat.generate(ctx)
        self._assert_clean(cm.exception)

    def test_missing_snapshot_exception_clean(self):
        ctx = self.prep("pub_a")
        with self.assertRaises(PublicationError) as cm:
            compat.generate(ctx)
        self._assert_clean(cm.exception)

    def test_cli_stderr_is_clean(self):
        import subprocess
        import sys

        script = Path(__file__).resolve().parents[3] / "engine" / "scripts" / "publication_snapshot.py"
        env = dict(os.environ)
        env.update(self.env)
        proc = subprocess.run(
            [
                sys.executable, str(script),
                "--workspace", str(self.base), "--section", SECTION,
                "build", "--legacy-source", str(self.legacy),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        for leak in self._leak_strings():
            self.assertNotIn(leak, proc.stderr, f"stderr leaks {leak!r}")


# ---------------------------------------------------------------------------
# Final: reconcile scoped to a single publication
# ---------------------------------------------------------------------------


class ReconcileFilterTest(C1TestCase):
    def _digest(self, dest) -> dict[str, bytes]:
        return {
            path.relative_to(dest).as_posix(): path.read_bytes()
            for path in sorted(dest.rglob("*"))
            if path.is_file()
        }

    def _events_for(self, ctx, pub) -> list:
        return [e for e in ctx.ledger().read_events() if e.get("publicationId") == pub]

    def test_reconcile_single_publication_ignores_others(self):
        ctx_a, _, _ = self.approve_flow("pub_a")
        ctx_c, _, _ = self.approve_flow("pub_c")

        ctx_b = self.prep("pub_b")
        result = builder.build_draft(ctx_b)
        builder.review_draft(ctx_b, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        real_append = LifecycleLedger.append

        def crash_on_approved(self, event_type, publication_id, **kwargs):
            if event_type == "approved":
                raise RuntimeError("crash before ledger append")
            return real_append(self, event_type, publication_id, **kwargs)

        with mock.patch.object(LifecycleLedger, "append", crash_on_approved):
            with self.assertRaises(RuntimeError):
                builder.approve_draft(ctx_b, result.review_hash, "approver-a", "approve", content_hash=result.content_hash)
        self.assertEqual(ctx_b.ledger().current_state("pub_b"), "reviewed")

        before_a = self._digest(ctx_a.destination_dir())
        before_c = self._digest(ctx_c.destination_dir())
        events_before = {
            "pub_a": self._events_for(ctx_a, "pub_a"),
            "pub_c": self._events_for(ctx_c, "pub_c"),
        }

        actions = builder.reconcile(ctx_b, publication_id="pub_b")
        self.assertTrue(any("ledger-reconciled:pub_b" in a for a in actions), actions)
        self.assertFalse(any("pub_a" in a or "pub_c" in a for a in actions), actions)
        self.assertEqual(ctx_b.ledger().current_state("pub_b"), "approved")
        self.assertEqual(self._digest(ctx_a.destination_dir()), before_a, "first snapshot untouched")
        self.assertEqual(self._digest(ctx_c.destination_dir()), before_c, "third snapshot untouched")
        self.assertEqual(self._events_for(ctx_a, "pub_a"), events_before["pub_a"], "first ledger untouched")
        self.assertEqual(self._events_for(ctx_c, "pub_c"), events_before["pub_c"], "third ledger untouched")

    def test_reconcile_nonexistent_id_is_clear_error(self):
        ctx, content_hash, dest = self.approve_flow("pub_a")
        with self.assertRaises(PublicationError) as cm:
            builder.reconcile(ctx, publication_id="pub_missing")
        self.assertIn("pub_missing", str(cm.exception))

    def test_reconcile_invalid_id_rejected(self):
        ctx = self.prep()
        with self.assertRaises(Exception):
            builder.reconcile(ctx, publication_id="../escape")

    def test_reconcile_scoped_is_idempotent(self):
        ctx_a, _, _ = self.approve_flow("pub_a")
        ctx_b, _, _ = self.approve_flow("pub_b")
        first = builder.reconcile(ctx_b, publication_id="pub_b")
        second = builder.reconcile(ctx_b, publication_id="pub_b")
        self.assertEqual(first, [])
        self.assertEqual(second, [])


# ---------------------------------------------------------------------------
# Final: lifecycle transitions serialize with compatibility generation via the
# same publication lock (publication lock -> lifecycle lock); views are never
# published after a terminal event.
# ---------------------------------------------------------------------------


class TransitionCompatSerializationTest(C1TestCase):
    def _base_env(self, base):
        return {
            "ACADGRAD_PRIVATE_ROOT": str(base / "roots" / "priv"),
            "ACADGRAD_STATE_ROOT": str(base / "roots" / "state"),
            "ACADGRAD_PUBLICATIONS_ROOT": str(base / "roots" / "pub"),
            "ACADGRAD_TEMP_ROOT": str(base / "roots" / "tmp"),
        }

    def _approve_in(self, base, env, pub, **build_kwargs):
        legacy = base / "legacy"
        write(legacy / "manifest.json", {"course": {"id": SECTION}, "schemaVersion": 1})
        write(legacy / "course/course.json", DEFAULT_COURSE)
        write(legacy / "course/students.json", {"items": DEFAULT_STUDENTS})
        write(legacy / "course/evaluations.json", {"items": DEFAULT_EVALUATIONS})
        write(legacy / "course/results.json", {"items": DEFAULT_RESULTS})
        write(legacy / "course/course-summary.json", {"students": 2, "evaluations": 2})
        IdentityStore(Path(env["ACADGRAD_STATE_ROOT"]) / "identity").ensure_many(
            [
                {"external": {"rut": RUT_A}, "display_name": f"S {RUT_A}"},
                {"external": {"rut": RUT_B}, "display_name": f"S {RUT_B}"},
            ]
        )
        ctx = builder.BuildContext.resolve(
            base, SECTION, publication_id=pub, env=env, clock=Clock(env=env),
            legacy_source=legacy,
        )
        result = builder.build_draft(ctx, **build_kwargs)
        builder.review_draft(ctx, result.review_hash, "reviewer-a", content_hash=result.content_hash)
        builder.approve_draft(ctx, result.review_hash, "approver-a", "approve", content_hash=result.content_hash)
        return ctx, result.content_hash

    def test_generate_vs_terminal_never_publishes_after_terminal(self):
        """Race ``compat.generate`` against a terminal transition on the same
        publication. Both are serialized by the publication lock, so a generate
        that wins the lock publishes while the snapshot is approved and the
        terminal event is appended afterwards; a generate that loses sees the
        terminal state and publishes nothing. Views are never produced after the
        terminal event."""
        seen_views = 0
        seen_no_views = 0
        for terminal_kind in ("revoked", "corrected"):
            for _ in range(8):
                base = Path(tempfile.mkdtemp(prefix="c1-race-"))
                self.addCleanup(force_rmtree, base)
                env = self._base_env(base)
                self._approve_in(base, env, "pub_a")
                if terminal_kind == "corrected":
                    self._approve_in(base, env, "pub_b", **{"corrects_publication_id": "pub_a"})
                jobs = [
                    ("compat_generate", str(base), SECTION, "pub_a", env),
                    ("compat_revoke" if terminal_kind == "revoked" else "compat_corrected", str(base), SECTION, "pub_a", env),
                ]
                results = _run_workers_compat(jobs)
                generate_outcome = results[0][0]
                self.assertEqual(results[1][0], "ok", results)

                ctx = builder.BuildContext.resolve(
                    base, SECTION, publication_id="pub_a", env=env, clock=Clock(env=env),
                    legacy_source=base / "legacy",
                )
                terminal = [
                    e for e in ctx.ledger().read_events()
                    if e.get("publicationId") == "pub_a" and e.get("event") == terminal_kind
                ]
                self.assertEqual(len(terminal), 1, results)
                view_root = compat.section_compat_dir(ctx, SECTION) / "pub_a"
                if view_root.is_dir():
                    envelope = json.loads((view_root / "grades.json").read_text(encoding="utf-8"))
                    self.assertEqual(envelope["sourcePublicationId"], "pub_a")
                    self.assertLessEqual(
                        envelope["generatedAt"], terminal[0]["at"],
                        f"views published after the {terminal_kind} event",
                    )
                    self.assertEqual(generate_outcome, "ok", results)
                    seen_views += 1
                else:
                    self.assertEqual(generate_outcome, "PublicationError", results)
                    seen_no_views += 1
        self.assertGreaterEqual(seen_views, 1, "the race must exercise the generate-wins ordering")
        self.assertGreaterEqual(seen_no_views, 1, "the race must exercise the terminal-first ordering")


# ---------------------------------------------------------------------------


if __name__ == "__main__":

    unittest.main()
