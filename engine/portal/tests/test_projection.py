"""C4 deterministic per-student projection tests against real snapshots."""

from __future__ import annotations

import pytest

from portal.projection import (
    build_projection,
    projection_hash,
    subject_student_ids,
)


def _opaque_id(identity_store, rut):
    return identity_store.resolve_by_external("rut", rut)


class TestLegacyProjection:
    def test_only_own_results(self, portal_fixture):
        stu_a = _opaque_id(portal_fixture.identity_store, "11111111-1")
        stu_b = _opaque_id(portal_fixture.identity_store, "22222222-2")
        view_a = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        view_b = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_b,
            "legacy-effective",
        )
        assert view_a["studentId"] == stu_a
        assert view_b["studentId"] == stu_b
        assert view_a["studentId"] != view_b["studentId"]
        for assessment in view_a["assessments"]:
            assert assessment["score"] is not None
        for assessment in view_b["assessments"]:
            # B has one evaluated and one pending result.
            assert assessment["status"] in ("Evaluada", "En revisión")

    def test_scores_are_canonical_strings(self, portal_fixture):
        stu_a = _opaque_id(portal_fixture.identity_store, "11111111-1")
        view = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        for assessment in view["assessments"]:
            if assessment["score"] is not None:
                assert isinstance(assessment["score"], str)
                assert "." in assessment["score"]
            if assessment["grade"] is not None:
                assert isinstance(assessment["grade"], str)

    def test_sorted_by_assessment_id(self, portal_fixture):
        stu_a = _opaque_id(portal_fixture.identity_store, "11111111-1")
        view = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        ids = [a["assessmentId"] for a in view["assessments"]]
        assert ids == sorted(ids)

    def test_deterministic_hash(self, portal_fixture):
        stu_a = _opaque_id(portal_fixture.identity_store, "11111111-1")
        v1 = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        v2 = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        assert projection_hash(v1) == projection_hash(v2)

    def test_no_pii_in_projection(self, portal_fixture):
        stu_a = _opaque_id(portal_fixture.identity_store, "11111111-1")
        view = build_projection(
            portal_fixture.section_id,
            portal_fixture.publication_id,
            portal_fixture.snapshot_dir,
            stu_a,
            "legacy-effective",
        )
        blob = str(view)
        assert "11111111-1" not in blob
        assert "Ana" not in blob
        assert "example.test" not in blob
        assert "Buen trabajo" in blob  # feedback preserved (allowed by contract)


class TestC2Projection:
    def test_final_outcome_present(self, c2_fixture):
        stu_a = _opaque_id(c2_fixture.identity_store, "11111111-1")
        view = build_projection(
            c2_fixture.section_id,
            c2_fixture.publication_id,
            c2_fixture.snapshot_dir,
            stu_a,
            "grade-policy-effective",
        )
        assert view["snapshotMode"] == "grade-policy-effective"
        assert view["finalOutcome"] is not None
        assert isinstance(view["finalOutcome"]["value"], str)
        assert view["finalOutcome"]["finalizable"] is True

    def test_mode_specific_not_mixed(self, c2_fixture):
        stu_a = _opaque_id(c2_fixture.identity_store, "11111111-1")
        view = build_projection(
            c2_fixture.section_id,
            c2_fixture.publication_id,
            c2_fixture.snapshot_dir,
            stu_a,
            "grade-policy-effective",
        )
        assert view["finalOutcome"] is not None

    def test_subjects_match_roster(self, portal_fixture):
        ids = subject_student_ids(portal_fixture.snapshot_dir)
        assert len(ids) == 2
        assert portal_fixture.identity_store.resolve_by_external("rut", "11111111-1") in ids
