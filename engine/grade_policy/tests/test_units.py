"""C2 unit propagation tests: typed resolve_output_unit across the DAG.

The validator propagates declared assessment units through every operator and
the engine preserves the same units at runtime, so the static inference never
disagrees with execution.
"""

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
from grade_policy.errors import SchemaValidationError, SemanticValidationError, UnitMismatchError


def policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "units",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["a", "b"],
        "assessmentUnits": {"a": "percent", "b": "percent"},
        "stages": {},
        "resultStageId": "final",
    }
    doc.update(overrides)
    return doc


def stage(sid: str, phase: str, operator: str, inputs, **extra) -> dict:
    payload = {"id": sid, "phase": phase, "operator": operator, "inputs": inputs}
    payload.update(extra)
    return payload


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


class UnitChainTest(unittest.TestCase):
    def test_percent_weighted_cap(self) -> None:
        doc = policy(
            resultStageId="cap",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]),
                "cap": stage("cap", "adjustment", "cap", [{"ref": "w"}], params={"max": "80"}),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(a=(90, "percent"), b=(70, "percent")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "percent")
        self.assertEqual(out.value.value, Decimal("80"))

    def test_grade_weighted_round(self) -> None:
        doc = policy(
            assessments=["a", "b"],
            assessmentUnits={"a": "grade", "b": "grade"},
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 2}),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(a=(6.5, "grade"), b=(5.5, "grade")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "grade")
        self.assertEqual(out.value.value, Decimal("6.00"))

    def test_points_sum_floor(self) -> None:
        doc = policy(
            assessments=["a", "b"],
            assessmentUnits={"a": "points", "b": "points"},
            resultStageId="floor",
            stages={
                "s": stage("s", "aggregation", "sum", [{"ref": "a"}, {"ref": "b"}]),
                "floor": stage("floor", "adjustment", "floor", [{"ref": "s"}], params={"min": "0"}),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(a=(10, "points"), b=(-5, "points")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "points")
        self.assertEqual(out.value.value, Decimal("5"))

    def test_static_unit_propagation_agrees_with_runtime(self) -> None:
        from grade_policy.units import propagate_units

        doc = policy(
            resultStageId="cap",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]),
                "cap": stage("cap", "adjustment", "cap", [{"ref": "w"}], params={"max": "80"}),
            },
        )
        loaded = load_policy(doc)
        units = propagate_units(loaded)
        self.assertEqual(units["w"], "percent")
        self.assertEqual(units["cap"], "percent")
        out = calculate(loaded, inputs_for(a=(90, "percent"), b=(70, "percent")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, units["cap"])

    def test_piecewise_scale_uses_explicit_output_unit(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": stage(
                    "scale", "conversion", "piecewiseLinearScale", [{"ref": "a"}],
                    params={"outputUnit": "grade",
                            "pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}]},
                ),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(a=(90, "percent")), {"subjectId": "S"})
        self.assertEqual(out.value.unit, "grade")


class UnitValidationTest(unittest.TestCase):
    def test_static_mismatch_rejected(self) -> None:
        # piecewiseLinearScale emits grade; a second piecewiseLinearScale
        # requires percent as input -> static mismatch.
        doc = policy(
            resultStageId="scale2",
            stages={
                "scale1": stage("scale1", "conversion", "piecewiseLinearScale", [{"ref": "a"}],
                                params={"outputUnit": "grade",
                                        "pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}]}),
                "scale2": stage("scale2", "conversion", "piecewiseLinearScale", [{"ref": "scale1"}],
                                params={"outputUnit": "grade",
                                        "pairs": [{"from": None, "to": 1}, {"from": 4, "to": 7}]}),
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_static_mixed_declared_units_rejected(self) -> None:
        doc = policy(
            assessments=["a", "b"],
            assessmentUnits={"a": "percent", "b": "points"},
            resultStageId="w",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]),
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_unknown_declared_unit_rejected(self) -> None:
        doc = policy(assessmentUnits={"a": "furlongs"})
        with self.assertRaises(SchemaValidationError):
            load_policy(doc)

    def test_output_unit_missing_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": stage("scale", "conversion", "piecewiseLinearScale", [{"ref": "a"}],
                               params={"pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}]}),
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_runtime_mismatch_rejected(self) -> None:
        doc = policy(resultStageId="w",
                     stages={
                         "w": stage("w", "aggregation", "weightedAverage",
                                    [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]),
                     })
        loaded = load_policy(doc)
        with self.assertRaises(UnitMismatchError):
            calculate(loaded, inputs_for(a=(90, "percent"), b=(70, "points")), {"subjectId": "S"})

    def test_declared_unit_mismatch_runtime_rejected(self) -> None:
        doc = policy(resultStageId="w",
                     stages={
                         "w": stage("w", "aggregation", "weightedAverage",
                                    [{"ref": "a", "weight": "1"}]),
                     })
        loaded = load_policy(doc)
        with self.assertRaises(UnitMismatchError):
            calculate(loaded, inputs_for(a=(90, "points")), {"subjectId": "S"})


if __name__ == "__main__":
    unittest.main()
