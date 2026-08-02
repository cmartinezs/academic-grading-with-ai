"""C2 missing-policy semantics: fail, zero, excludeAndRenormalize, minimumOutput,
pending and notApplicable, each with the right typed state and trace decisions."""

from __future__ import annotations

import unittest
from decimal import Decimal

from grade_policy import (
    AcademicValue,
    AssessmentInput,
    NormalizedInputs,
    calculate,
    load_policy,
)
from grade_policy.errors import (
    MissingInputError,
    OutOfRangeError,
    SemanticValidationError,
    UnitMismatchError,
)


def policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "missing",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["a", "b"],
        "assessmentUnits": {"a": "percent", "b": "percent"},
        "stages": {},
        "resultStageId": "final",
    }
    doc.update(overrides)
    return doc


def weighted(sid: str = "w", policy: str = "fail", result: str = "w", **params) -> dict:
    return {
        "id": sid,
        "phase": "aggregation",
        "operator": "weightedAverage",
        "inputs": [{"ref": "a", "weight": "0.6"}, {"ref": "b", "weight": "0.4"}],
        "missingPolicy": policy,
        "params": params,
    }


def inputs_for(**values) -> NormalizedInputs:
    assessments = {
        ref: AssessmentInput(
            ref,
            value is not None,
            AcademicValue.from_scalar(value, unit) if value is not None else None,
        )
        for ref, (value, unit) in values.items()
    }
    return NormalizedInputs(subject_id="S", assessments=assessments)


class ZeroPolicyTest(unittest.TestCase):
    def test_zero_preserves_percent_unit(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "zero")})
        out = calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("48"))
        self.assertEqual(out.value.unit, "percent")

    def test_zero_preserves_points_unit(self) -> None:
        doc = policy(
            assessmentUnits={"a": "points", "b": "points"},
            resultStageId="w",
            stages={"w": weighted("w", "zero")},
        )
        out = calculate(load_policy(doc), inputs_for(a=(10, "points"), b=(None, "points")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "points")
        self.assertEqual(out.value.value, Decimal("6"))

    def test_zero_preserves_grade_unit(self) -> None:
        doc = policy(
            assessmentUnits={"a": "grade", "b": "grade"},
            resultStageId="w",
            stages={"w": weighted("w", "zero")},
        )
        out = calculate(load_policy(doc), inputs_for(a=(6, "grade"), b=(None, "grade")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "grade")
        self.assertEqual(out.value.value, Decimal("3.6"))

    def test_zero_preserves_scalar_unit(self) -> None:
        doc = policy(
            assessmentUnits={"a": "scalar", "b": "scalar"},
            resultStageId="w",
            stages={"w": weighted("w", "zero")},
        )
        out = calculate(load_policy(doc), inputs_for(a=(8, "scalar"), b=(None, "scalar")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "scalar")
        self.assertEqual(out.value.value, Decimal("4.8"))

    def test_zero_all_inputs_missing_uses_declared_unit(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "zero")})
        out = calculate(load_policy(doc), inputs_for(a=(None, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("0"))
        self.assertEqual(out.value.unit, "percent")
        decisions = {md.ref: md for ev in out.stages for md in ev.missing_decisions}
        self.assertEqual(set(decisions), {"a", "b"})
        self.assertEqual(decisions["a"].policy, "zero")
        self.assertEqual(decisions["a"].resulting_state, "value")

    def test_zero_all_missing_undeclared_unit_rejected(self) -> None:
        doc = policy(assessmentUnits={}, resultStageId="w", stages={"w": weighted("w", "zero")})
        with self.assertRaises(UnitMismatchError):
            calculate(load_policy(doc), inputs_for(a=(None, "percent"), b=(None, "percent")), {"subjectId": "S"})

    def test_zero_mixed_units_rejected(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "zero")})
        with self.assertRaises(UnitMismatchError):
            calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(70, "points")), {"subjectId": "S"})


class FailPolicyTest(unittest.TestCase):
    def test_fail_raises_on_missing(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "fail")})
        with self.assertRaises(MissingInputError):
            calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})


class ExcludeAndRenormalizeTest(unittest.TestCase):
    def test_renormalizes_weights_and_records_decisions(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "excludeAndRenormalize")})
        out = calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        # 0.6 renormalized to 1.0 over 80 -> 80
        self.assertEqual(out.value.value, Decimal("80"))
        self.assertEqual(out.value.unit, "percent")
        ev = out.stages[0]
        self.assertEqual(len(ev.missing_decisions), 1)
        md = ev.missing_decisions[0]
        self.assertEqual(md.ref, "b")
        self.assertEqual(md.policy, "excludeAndRenormalize")
        self.assertEqual(md.original_weight, Decimal("0.4"))
        self.assertEqual(md.effective_weight, Decimal("0"))
        self.assertEqual(md.total_before, Decimal("1"))
        self.assertEqual(md.resulting_state, "excluded")
        self.assertTrue(any("priorTotal" in d for d in ev.decisions))

    def test_no_present_inputs_is_pending(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "excludeAndRenormalize")})
        out = calculate(load_policy(doc), inputs_for(a=(None, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")
        self.assertFalse(out.finalizable)
        self.assertEqual(out.state, "pending")


class MinimumOutputTest(unittest.TestCase):
    def test_minimum_output_uses_explicit_value_and_unit(self) -> None:
        doc = policy(
            resultStageId="w",
            stages={"w": weighted("w", "minimumOutput", minimum={"value": "40", "unit": "percent"})},
        )
        out = calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("40"))
        self.assertEqual(out.value.unit, "percent")

    def test_minimum_output_requires_param(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "minimumOutput")})
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_minimum_output_not_available_on_round(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": weighted("w", "fail"),
                "final": {
                    "id": "final",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "w"}],
                    "params": {"decimalPlaces": 1},
                    "missingPolicy": "minimumOutput",
                },
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)


class PendingAndNotApplicableTest(unittest.TestCase):
    def test_pending_produces_non_finalizable_outcome(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "pending")})
        out = calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")
        self.assertFalse(out.finalizable)
        self.assertEqual(out.state, "pending")
        self.assertIsNone(out.value)

    def test_not_applicable_distinct_from_pending(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "notApplicable")})
        out = calculate(load_policy(doc), inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "notApplicable")
        self.assertFalse(out.finalizable)
        self.assertEqual(out.state, "notApplicable")
        self.assertIsNone(out.value)


class WeightedAveragePolicyMatrixTest(unittest.TestCase):
    def test_allowed_matrix_loads(self) -> None:
        for policy_name in ("fail", "zero", "excludeAndRenormalize", "minimumOutput", "pending", "notApplicable"):
            params = {"minimum": {"value": "40", "unit": "percent"}} if policy_name == "minimumOutput" else {}
            doc = policy(resultStageId="w", stages={"w": weighted("w", policy_name, **params)})
            loaded = load_policy(doc)
            self.assertEqual(loaded.stages["w"].missing_policy, policy_name)

    def test_disallowed_policy_rejected(self) -> None:
        doc = policy(resultStageId="w", stages={"w": weighted("w", "excludeAndRenormalize")})
        stages = doc["stages"]
        stages["w"]["operator"] = "round"
        stages["w"]["phase"] = "finalization"
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)


class PiecewiseZeroTest(unittest.TestCase):
    """piecewiseLinearScale with missingPolicy=zero: the zero is created in the
    *input* ref's expected unit (never params.outputUnit), the range check runs
    before scaling, and reject/clamp behave exactly like the present path."""

    def _doc(self, breakpoints=None, outside_range: str = "clamp") -> dict:
        return policy(
            resultStageId="scale",
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "a"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": outside_range,
                        "breakpoints": breakpoints
                        or [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    },
                    "missingPolicy": "zero",
                }
            },
        )

    def test_piecewise_zero_input_percent_output_grade(self) -> None:
        doc = self._doc()
        out = calculate(load_policy(doc), inputs_for(a=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.unit, "grade")
        self.assertEqual(out.value.value, Decimal("1"))

    def test_piecewise_zero_within_range(self) -> None:
        out = calculate(
            load_policy(self._doc()),
            inputs_for(a=(None, "percent")),
            {"subjectId": "S"},
        )
        # zero=0 lies inside [0, 100]; scale(0) hits the first breakpoint y=1.
        self.assertEqual(out.value.value, Decimal("1"))

    def test_piecewise_zero_outside_range_clamp(self) -> None:
        out = calculate(
            load_policy(self._doc(breakpoints=[{"x": "10", "y": "2"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}])),
            inputs_for(a=(None, "percent")),
            {"subjectId": "S"},
        )
        # zero=0 < first breakpoint x=10; clamp yields the low extreme y=2.
        self.assertEqual(out.value.value, Decimal("2"))
        self.assertEqual(out.value.unit, "grade")

    def test_piecewise_zero_outside_range_reject(self) -> None:
        with self.assertRaises(OutOfRangeError):
            calculate(
                load_policy(self._doc(
                    breakpoints=[{"x": "10", "y": "2"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    outside_range="reject",
                )),
                inputs_for(a=(None, "percent")),
                {"subjectId": "S"},
            )

    def test_piecewise_zero_undeclared_input_unit_rejected(self) -> None:
        doc = self._doc()
        doc["assessmentUnits"] = {}
        with self.assertRaises(UnitMismatchError):
            calculate(load_policy(doc), inputs_for(a=(None, "percent")), {"subjectId": "S"})

    def test_piecewise_zero_trace_preserves_decision(self) -> None:
        out = calculate(
            load_policy(self._doc()),
            inputs_for(a=(None, "percent")),
            {"subjectId": "S"},
        )
        ev = out.stages[0]
        self.assertEqual(len(ev.missing_decisions), 1)
        md = ev.missing_decisions[0]
        self.assertEqual(md.ref, "a")
        self.assertEqual(md.policy, "zero")
        self.assertEqual(md.resulting_state, "value")
        self.assertEqual(ev.state, "value")


if __name__ == "__main__":
    unittest.main()
