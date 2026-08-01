#!/usr/bin/env python3
"""C1 self-check runner: runs the unittest suite plus a synthetic E2E scenario.

Used by ``./scripts/publication-snapshot.sh test`` and CI. Exit code is the
unittest result code (0 = all green).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
sys.path.insert(0, str(ENGINE))


def run_unittests() -> int:
    os.chdir(ENGINE)
    suite = unittest.defaultTestLoader.discover("publication.tests", top_level_dir=".")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_e2e() -> None:
    """Synthetic end-to-end scenario; never touches real data."""
    from c0.identity import IdentityStore

    from publication import builder, compat
    from publication.clock import Clock

    base = Path(tempfile.mkdtemp(prefix="c1-e2e-"))
    try:
        legacy = base / "legacy"
        roots = base / "roots"
        env = {
            "ACADGRAD_PRIVATE_ROOT": str(roots / "priv"),
            "ACADGRAD_STATE_ROOT": str(roots / "state"),
            "ACADGRAD_PUBLICATIONS_ROOT": str(roots / "pub"),
            "ACADGRAD_TEMP_ROOT": str(roots / "tmp"),
            "SOURCE_DATE_EPOCH": "1700000000",
        }

        def write(path: Path, payload) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                __import__("json").dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        course = {
            "course": {"name": "FP2111-S1", "title": "E2E"},
            "defaults": {"approvalThreshold": 60, "grading": {"minGrade": 1, "passingGrade": 4, "maxGrade": 7, "passingPercent": 60}, "presentationWeight": 60, "examWeight": 40},
        }
        write(legacy / "manifest.json", {"course": {"id": "FP2111-S1"}, "schemaVersion": 1})
        write(legacy / "course/course.json", course)
        write(legacy / "course/students.json", {"items": [{"id": "11111111-1", "rut": "11111111-1", "name": "Ana"}]})
        write(legacy / "course/evaluations.json", {"items": [{"id": "ev1", "title": "EV1", "weight": 100, "type": "evaluacion", "forms": ["A"]}]})
        write(
            legacy / "course/results.json",
            {"items": [{"studentId": "11111111-1", "evaluationId": "ev1", "form": "A", "status": "Evaluada", "score": 80.0, "grade": 6.0, "resultPath": "x", "finalFeedback": "OK", "ies": []}]},
        )
        write(legacy / "course/course-summary.json", {"students": 1, "evaluations": 1})

        store = IdentityStore(roots / "state/identity")
        store.ensure_many([{"external": {"rut": "11111111-1"}, "display_name": "Ana"}])

        ctx = builder.BuildContext.resolve(
            base, "FP2111-S1", publication_id="pub_e2e01", env=env, clock=Clock(env=env), legacy_source=legacy
        )
        result = builder.build_draft(ctx)
        report = builder.verify(ctx, "staging")
        assert report.passed(), [f.message for f in report.findings]
        builder.review_draft(ctx, result.content_hash, "reviewer-a")
        dest = builder.approve_draft(ctx, result.content_hash, "approver-a", "approve")
        assert dest.is_dir(), "approved snapshot must exist"
        assert builder.verify(ctx, "approved").passed()
        ctx.ledger().append("published", "pub_e2e01", actor="ops", receipt="e2e-rcpt")
        assert ctx.ledger().current_state("pub_e2e01") == "published"
        assert compat.generate(ctx) != []
        print(f"E2E OK: {ctx.publication_id} -> {result.content_hash}")
    finally:
        for path in base.rglob("*"):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        __import__("shutil").rmtree(base, ignore_errors=True)


def main() -> int:
    code = run_unittests()
    run_e2e()
    return code


if __name__ == "__main__":
    sys.exit(main())
