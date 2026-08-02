"""C2 canonical boundary: the authority frontier between canonical/results.json
and the grade policy engine (snapshot mode).

Covers:

- explicit ``assessmentUnits``: every assessment the policy reads must declare
  its unit; no implicit ``percent`` fallback;
- attempt selection: a second result for the same ``(studentId, assessmentId)``
  is rejected with a typed, sanitized error (array order is never a selection
  policy — no implicit first/last/best);
- invalid score handling: ``null``/empty is missing; anything non-finite or
  unparseable is a typed data error, never converted into a missing policy;
- the C1 structural precondition so ``build_c2_payloads`` is never exercised
  against incomplete canonical structures.

All data is synthetic; no PII and no real snapshots.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from grade_policy import load_policy
from grade_policy.errors import (
    CanonicalFormatError,
    DuplicateAttemptError,
    InvalidScoreError,
    SemanticValidationError,
)
from grade_policy.snapshot import build_c2_payloads


def policy(*, assessments=("a", "b"), units=None, stages=None, result_stage="final") -> dict:
    declared = units if units is not None else {aid: "percent" for aid in assessments}
    return {
        "schemaVersion": "1.0.0",
        "policyId": "boundary",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": list(assessments),
        "assessmentUnits": declared,
        "resultStageId": result_stage,
        "stages": stages
        if stages is not None
        else {
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [
                    {"ref": aid, "weight": "0.5"} for aid in assessments
                ],
            },
            "final": {
                "id": "final",
                "phase": "finalization",
                "operator": "round",
                "inputs": [{"ref": "w"}],
                "params": {"decimalPlaces": 2, "mode": "halfUp"},
            },
        },
    }


def canonical_for(rows, *, assessments=("a", "b"), student_ids=("stu_a1b2c3",)) -> dict:
    return {
        "canonical/assessments.json": {
            "schemaVersion": "1.0.0",
            "sectionId": "SEC",
            "assessments": [{"assessmentId": aid} for aid in assessments],
        },
        "canonical/subjects.json": {
            "schemaVersion": "1.0.0",
            "sectionId": "SEC",
            "subjects": [{"studentId": sid} for sid in student_ids],
        },
        "canonical/results.json": {
            "schemaVersion": "1.0.0",
            "sectionId": "SEC",
            "results": rows,
        },
    }


def row(
    sid: str,
    aid: str,
    score,
    *,
    status: str = "Evaluada",
    attempt: int = 1,
    **extra,
) -> dict:
    payload = {
        "studentId": sid,
        "assessmentId": aid,
        "attemptId": f"att_a1b2c3d4e5f6{aid.lower()}{attempt:02d}"[:22],
        "status": status,
        "score": score,
        "components": [],
    }
    payload.update(extra)
    return payload


def outcome_value(payloads):
    outcomes = payloads["canonical/outcomes.json"]
    return outcomes["subjectOutcomes"][0]


class ExplicitUnitsTest(unittest.TestCase):
    def test_all_units_declared_builds(self) -> None:
        doc = policy()
        payloads = build_c2_payloads(
            "SEC", canonical_for([row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]), doc
        )
        outcome = outcome_value(payloads)
        self.assertEqual(outcome["status"], "finalized")
        self.assertEqual(outcome["value"]["unit"], "percent")

    def test_missing_unit_rejected(self) -> None:
        doc = policy(units={"a": "percent"})
        with self.assertRaises(SemanticValidationError) as cm:
            build_c2_payloads(
                "SEC", canonical_for([row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]), doc
            )
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("never guesses" in m and "b" in m for m in messages),
            messages,
        )

    def test_no_unit_silently_falls_back_to_percent(self) -> None:
        """A policy with a score that would parse as percent must still fail when
        the unit is undeclared: snapshot mode never guesses ``percent``."""
        doc = policy(units={"a": "percent"})
        with self.assertRaises(SemanticValidationError):
            build_c2_payloads(
                "SEC",
                canonical_for([row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", "85")]),
                doc,
            )

    def test_units_preserved_percent(self) -> None:
        payloads = build_c2_payloads(
            "SEC", canonical_for([row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]), policy()
        )
        self.assertEqual(outcome_value(payloads)["value"]["unit"], "percent")

    def test_units_preserved_grade(self) -> None:
        doc = policy(
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "a"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": "clamp",
                        "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    },
                }
            },
            result_stage="scale",
        )
        payloads = build_c2_payloads(
            "SEC", canonical_for([row("stu_a1b2c3", "a", 80)]), doc
        )
        outcome = outcome_value(payloads)
        self.assertEqual(outcome["status"], "finalized")
        self.assertEqual(outcome["value"]["unit"], "grade")
        self.assertEqual(Decimal(outcome["value"]["value"]), Decimal("5.5"))

    def test_units_preserved_points(self) -> None:
        doc = policy(
            assessments=("a", "b"),
            units={"a": "points", "b": "points"},
            stages={
                "s": {
                    "id": "s",
                    "phase": "aggregation",
                    "operator": "sum",
                    "inputs": [{"ref": "a"}, {"ref": "b"}],
                },
                "final": {
                    "id": "final",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "s"}],
                    "params": {"decimalPlaces": 2, "mode": "halfUp"},
                },
            },
        )
        payloads = build_c2_payloads(
            "SEC",
            canonical_for([row("stu_a1b2c3", "a", 10), row("stu_a1b2c3", "b", 5)]),
            doc,
        )
        outcome = outcome_value(payloads)
        self.assertEqual(outcome["value"]["unit"], "points")
        self.assertEqual(Decimal(outcome["value"]["value"]), Decimal("15.00"))

    def test_units_preserved_level_condition(self) -> None:
        """A level assessment is fed with unit level (never percent): the
        levelAtLeast gate must evaluate against the level value."""
        doc = policy(
            assessments=("a", "lvl"),
            units={"a": "percent", "lvl": "level"},
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "a", "weight": "1"}],
                },
                "final": {
                    "id": "final",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "w"}],
                    "params": {"decimalPlaces": 2, "mode": "halfUp"},
                    "condition": {
                        "kind": "levelAtLeast",
                        "params": {"ref": "lvl", "level": "4", "levels": ["1", "2", "3", "4", "5", "6", "7"]},
                    },
                },
            },
        )
        rows = [
            row("stu_a1b2c3", "a", 80),
            row("stu_a1b2c3", "lvl", 5),
        ]
        self.assertEqual(outcome_value(build_c2_payloads("SEC", canonical_for(rows, assessments=("a", "lvl")), doc))["status"], "finalized")
        rows_low = [
            row("stu_a1b2c3", "a", 80),
            row("stu_a1b2c3", "lvl", 3),
        ]
        low = build_c2_payloads("SEC", canonical_for(rows_low, assessments=("a", "lvl")), doc)
        self.assertEqual(outcome_value(low)["status"], "pending")


class AttemptSelectionTest(unittest.TestCase):
    def test_single_attempt_ok(self) -> None:
        rows = [row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]
        payloads = build_c2_payloads("SEC", canonical_for(rows), policy())
        self.assertEqual(outcome_value(payloads)["status"], "finalized")

    def test_two_attempts_rejected(self) -> None:
        rows = [
            row("stu_a1b2c3", "a", 70, attempt=1),
            row("stu_a1b2c3", "a", 85, attempt=2),
            row("stu_a1b2c3", "b", 90),
        ]
        with self.assertRaises(DuplicateAttemptError) as cm:
            build_c2_payloads("SEC", canonical_for(rows), policy())
        self.assertIn("duplicate canonical result", str(cm.exception))
        self.assertIn("a", str(cm.exception))

    def test_reversed_array_same_rejection(self) -> None:
        rows = [
            row("stu_a1b2c3", "a", 85, attempt=2),
            row("stu_a1b2c3", "a", 70, attempt=1),
            row("stu_a1b2c3", "b", 90),
        ]
        with self.assertRaises(DuplicateAttemptError):
            build_c2_payloads("SEC", canonical_for(rows), policy())

    def test_different_students_ok(self) -> None:
        rows = [
            row("stu_a1b2c3", "a", 70),
            row("stu_a1b2c3", "b", 90),
            row("stu_x9y8z7", "a", 60),
            row("stu_x9y8z7", "b", 80),
        ]
        payloads = build_c2_payloads(
            "SEC",
            canonical_for(rows, student_ids=("stu_a1b2c3", "stu_x9y8z7")),
            policy(),
        )
        subjects = sorted(o["subjectId"] for o in payloads["canonical/outcomes.json"]["subjectOutcomes"])
        self.assertEqual(subjects, ["stu_a1b2c3", "stu_x9y8z7"])

    def test_different_assessments_ok(self) -> None:
        rows = [
            row("stu_a1b2c3", "a", 70, attempt=1),
            row("stu_a1b2c3", "a", 85, attempt=2),
        ]
        # Same student, same assessment twice is rejected regardless of the rest.
        with self.assertRaises(DuplicateAttemptError):
            build_c2_payloads("SEC", canonical_for(rows), policy())


class InvalidScoreTest(unittest.TestCase):
    def test_null_score_is_missing(self) -> None:
        doc = policy()
        doc["stages"]["w"]["missingPolicy"] = "zero"
        rows = [row("stu_a1b2c3", "a", None), row("stu_a1b2c3", "b", 80)]
        payloads = build_c2_payloads("SEC", canonical_for(rows), doc)
        outcome = outcome_value(payloads)
        self.assertEqual(outcome["status"], "finalized")
        self.assertEqual(Decimal(outcome["value"]["value"]), Decimal("40.00"))

    def test_valid_number_used_as_decimal(self) -> None:
        rows = [row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]
        outcome = outcome_value(build_c2_payloads("SEC", canonical_for(rows), policy()))
        self.assertEqual(Decimal(outcome["value"]["value"]), Decimal("80.00"))

    def test_non_empty_invalid_rejected(self) -> None:
        rows = [row("stu_a1b2c3", "a", "abc"), row("stu_a1b2c3", "b", 90)]
        with self.assertRaises(InvalidScoreError) as cm:
            build_c2_payloads("SEC", canonical_for(rows), policy())
        self.assertNotIn("abc", str(cm.exception))

    def test_nan_rejected(self) -> None:
        rows = [row("stu_a1b2c3", "a", float("nan")), row("stu_a1b2c3", "b", 90)]
        with self.assertRaises(InvalidScoreError):
            build_c2_payloads("SEC", canonical_for(rows), policy())

    def test_infinity_rejected(self) -> None:
        rows = [row("stu_a1b2c3", "a", float("inf")), row("stu_a1b2c3", "b", 90)]
        with self.assertRaises(InvalidScoreError):
            build_c2_payloads("SEC", canonical_for(rows), policy())

    def test_string_nan_rejected(self) -> None:
        rows = [row("stu_a1b2c3", "a", "NaN"), row("stu_a1b2c3", "b", 90)]
        with self.assertRaises(InvalidScoreError):
            build_c2_payloads("SEC", canonical_for(rows), policy())


class CanonicalPreconditionTest(unittest.TestCase):
    def _valid(self, **overrides):
        rows = [row("stu_a1b2c3", "a", 70), row("stu_a1b2c3", "b", 90)]
        payload = canonical_for(rows)
        for key, value in overrides.items():
            payload[key] = value
        return payload

    def test_incomplete_result_rejected(self) -> None:
        bad = row("stu_a1b2c3", "a", 70)
        bad.pop("attemptId")
        payload = canonical_for([bad, row("stu_a1b2c3", "b", 90)])
        with self.assertRaises(CanonicalFormatError):
            build_c2_payloads("SEC", payload, policy())

    def test_missing_results_payload_rejected(self) -> None:
        payload = canonical_for([row("stu_a1b2c3", "a", 70)])
        payload.pop("canonical/results.json")
        with self.assertRaises(CanonicalFormatError):
            build_c2_payloads("SEC", payload, policy())

    def test_missing_header_rejected(self) -> None:
        payload = canonical_for([row("stu_a1b2c3", "a", 70)])
        del payload["canonical/results.json"]["schemaVersion"]
        with self.assertRaises(CanonicalFormatError):
            build_c2_payloads("SEC", payload, policy())

    def test_non_opaque_student_id_rejected(self) -> None:
        rows = [row("12.345.678-9", "a", 70), row("12.345.678-9", "b", 90)]
        with self.assertRaises(CanonicalFormatError):
            build_c2_payloads("SEC", canonical_for(rows), policy())

    def test_non_object_result_rejected(self) -> None:
        payload = canonical_for([row("stu_a1b2c3", "a", 70)])
        payload["canonical/results.json"]["results"].append("not-an-object")
        with self.assertRaises(CanonicalFormatError):
            build_c2_payloads("SEC", payload, policy())


if __name__ == "__main__":
    unittest.main()
