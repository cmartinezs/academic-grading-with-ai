"""C2 conformance suite: schema/semantic gates, operator and condition behavior.

All data is synthetic. No PII, no real snapshots.
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
from grade_policy.errors import (
    CycleError,
    EngineVersionError,
    GradePolicyError,
    MissingInputError,
    SchemaValidationError,
    SemanticValidationError,
    StageReferenceError,
    UnsupportedConditionError,
    UnsupportedOperatorError,
    WeightSumError,
)


def policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "conformance",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["presentation", "exam"],
        "stages": {},
        "resultStageId": "final",
    }
    doc.update(overrides)
    return doc


def simple_weighted(stage_id: str = "w") -> dict:
    return {
        "id": stage_id,
        "phase": "aggregation",
        "operator": "weightedAverage",
        "inputs": [
            {"ref": "presentation", "weight": "0.6"},
            {"ref": "exam", "weight": "0.4"},
        ],
    }


def inputs_for(**values) -> NormalizedInputs:
    assessments = {}
    for ref, score in values.items():
        assessments[ref] = AssessmentInput(
            assessment_id=ref,
            present=score is not None,
            value=AcademicValue.from_scalar(score, "percent") if score is not None else None,
        )
    return NormalizedInputs(subject_id="S", assessments=assessments)


class SchemaGateTest(unittest.TestCase):
    def test_valid_policy_loads(self) -> None:
        doc = policy(
            stages={
                "w": simple_weighted(),
                "final": {
                    "id": "final",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "w"}],
                    "params": {"decimalPlaces": 1},
                },
            }
        )
        loaded = load_policy(doc)
        self.assertEqual(loaded.policy_id, "conformance")
        self.assertEqual(loaded.result_stage_id, "final")

    def test_unknown_field_rejected(self) -> None:
        doc = policy(stages={"w": {**simple_weighted(), "when": "level>=4"}})
        with self.assertRaises(SchemaValidationError):
            load_policy(doc)

    def test_unknown_operator_rejected(self) -> None:
        doc = policy(
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "magicAverage",
                      "inputs": [{"ref": "presentation"}]}
            }
        )
        with self.assertRaises(UnsupportedOperatorError):
            load_policy(doc)

    def test_unknown_condition_rejected(self) -> None:
        doc = policy(
            stages={
                "w": {**simple_weighted(), "condition": {"kind": "whenFullMoon", "params": {}}}
            }
        )
        with self.assertRaises(UnsupportedConditionError):
            load_policy(doc)

    def test_missing_required_field_rejected(self) -> None:
        doc = policy(stages={"w": {"phase": "aggregation"}})
        with self.assertRaises(SchemaValidationError):
            load_policy(doc)

    def test_engine_version_too_new_rejected(self) -> None:
        doc = policy(engineMinVersion="99.0.0", stages={"w": simple_weighted()})
        with self.assertRaises(EngineVersionError):
            load_policy(doc)


class SemanticGateTest(unittest.TestCase):
    def test_cycle_rejected(self) -> None:
        doc = policy(
            resultStageId="a",
            stages={
                "a": {"id": "a", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "b"}]},
                "b": {"id": "b", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "a"}]},
            }
        )
        with self.assertRaises(CycleError):
            load_policy(doc)

    def test_self_reference_rejected(self) -> None:
        doc = policy(
            resultStageId="a",
            stages={
                "a": {"id": "a", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "a"}]}
            }
        )
        with self.assertRaises(CycleError):
            load_policy(doc)

    def test_unknown_ref_rejected(self) -> None:
        doc = policy(
            resultStageId="a",
            stages={"a": {"id": "a", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "nope"}]}}
        )
        with self.assertRaises(StageReferenceError):
            load_policy(doc)

    def test_dead_stage_rejected(self) -> None:
        doc = policy(
            stages={
                "final": {"id": "final", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "presentation"}]},
                "dead": {"id": "dead", "phase": "aggregation", "operator": "sum", "inputs": [{"ref": "exam"}]},
            }
        )
        with self.assertRaises(StageReferenceError):
            load_policy(doc)

    def test_result_stage_not_declared_rejected(self) -> None:
        doc = policy(resultStageId="missing", stages={"w": simple_weighted()})
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_round_not_allowed_in_aggregation(self) -> None:
        doc = policy(
            resultStageId="r",
            stages={"r": {"id": "r", "phase": "aggregation", "operator": "round",
                          "inputs": [{"ref": "presentation"}]}}
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_exclude_and_renormalize_not_allowed_in_sum(self) -> None:
        doc = policy(
            stages={
                "s": {"id": "s", "phase": "aggregation", "operator": "sum",
                      "inputs": [{"ref": "presentation"}, {"ref": "exam"}],
                      "missingPolicy": "excludeAndRenormalize"}
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_incompatible_unit_flow_rejected(self) -> None:
        doc = policy(
            resultStageId="scale2",
            stages={
                "scale1": {"id": "scale1", "phase": "conversion", "operator": "piecewiseLinearScale",
                           "inputs": [{"ref": "presentation"}],
                           "params": {"outputUnit": "grade", "pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}]}},
                "scale2": {"id": "scale2", "phase": "conversion", "operator": "piecewiseLinearScale",
                           "inputs": [{"ref": "scale1"}],
                           "params": {"outputUnit": "grade", "pairs": [{"from": None, "to": 1}, {"from": 4, "to": 7}]}},
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_piecewise_output_unit_missing_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {"id": "scale", "phase": "conversion", "operator": "piecewiseLinearScale",
                          "inputs": [{"ref": "presentation"}],
                          "params": {"pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}]}}
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)


class OperatorConformanceTest(unittest.TestCase):
    def test_weighted_average(self) -> None:
        doc = policy(resultStageId="w", stages={"w": simple_weighted()})
        out = calculate(load_policy(doc), inputs_for(presentation=80, exam=60), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("72"))
        self.assertEqual(out.value.unit, "percent")

    def test_weighted_average_missing_zero(self) -> None:
        doc = policy(
            resultStageId="w",
            stages={"w": {**simple_weighted(), "missingPolicy": "zero"}}
        )
        out = calculate(load_policy(doc), inputs_for(presentation=80, exam=None), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("48"))

    def test_weighted_average_missing_fail(self) -> None:
        doc = policy(resultStageId="w", stages={"w": simple_weighted()})
        with self.assertRaises(MissingInputError):
            calculate(load_policy(doc), inputs_for(presentation=80, exam=None), {"subjectId": "S"})

    def test_weighted_average_weights_not_one(self) -> None:
        doc = policy(
            resultStageId="w",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [
                        {"ref": "presentation", "weight": "0.1"},
                        {"ref": "exam", "weight": "0.1"},
                    ],
                }
            }
        )
        with self.assertRaises(WeightSumError):
            calculate(load_policy(doc), inputs_for(presentation=80, exam=60), {"subjectId": "S"})

    def test_sum(self) -> None:
        doc = policy(
            resultStageId="s",
            stages={"s": {"id": "s", "phase": "aggregation", "operator": "sum",
                          "inputs": [{"ref": "presentation"}, {"ref": "exam"}]}}
        )
        out = calculate(load_policy(doc), inputs_for(presentation=10, exam=20), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("30"))
        self.assertEqual(out.value.unit, "percent")

    def test_piecewise_linear_scale(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {"id": "scale", "phase": "conversion", "operator": "piecewiseLinearScale",
                          "inputs": [{"ref": "presentation"}],
                          "params": {"outputUnit": "grade", "pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}, {"from": 100, "to": 7}]}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=90), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("6.4"))
        self.assertEqual(out.value.unit, "grade")

    def test_piecewise_linear_scale_clamps_low(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {"id": "scale", "phase": "conversion", "operator": "piecewiseLinearScale",
                          "inputs": [{"ref": "presentation"}],
                          "params": {"outputUnit": "grade", "pairs": [{"from": None, "to": 1}, {"from": 50, "to": 4}, {"from": 100, "to": 7}]}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=20), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("1"))

    def test_additive_bonus(self) -> None:
        doc = policy(
            resultStageId="b",
            stages={
                "b": {"id": "b", "phase": "adjustment", "operator": "additiveBonus",
                      "inputs": [{"ref": "presentation"}], "params": {"bonus": "5"}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=80), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("85"))

    def test_replace_lowest_input(self) -> None:
        doc = policy(
            resultStageId="r",
            stages={
                "r": {"id": "r", "phase": "adjustment", "operator": "replaceLowestInput",
                      "inputs": [{"ref": "presentation"}, {"ref": "exam"}],
                      "params": {"replacement": "60"}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=70, exam=90), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("150"))

    def test_cap(self) -> None:
        doc = policy(
            resultStageId="c",
            stages={
                "c": {"id": "c", "phase": "adjustment", "operator": "cap",
                      "inputs": [{"ref": "presentation"}], "params": {"max": "100"}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=120), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("100"))

    def test_floor(self) -> None:
        doc = policy(
            resultStageId="f",
            stages={
                "f": {"id": "f", "phase": "adjustment", "operator": "floor",
                      "inputs": [{"ref": "presentation"}], "params": {"min": "0"}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=-5), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("0"))

    def test_round_modes(self) -> None:
        for mode, value, expected in (
            ("halfUp", "5.325", "5.33"),
            ("halfEven", "5.325", "5.32"),
            ("floor", "5.329", "5.32"),
            ("ceil", "5.321", "5.33"),
            ("truncate", "5.329", "5.32"),
        ):
            doc = policy(
                resultStageId="r",
                stages={
                    "r": {"id": "r", "phase": "finalization", "operator": "round",
                          "inputs": [{"ref": "presentation"}],
                          "params": {"decimalPlaces": 2, "mode": mode}}
                }
            )
            out = calculate(load_policy(doc), inputs_for(presentation=value), {"subjectId": "S"})
            self.assertEqual(str(out.value.value), expected, msg=f"mode={mode}")


class ConditionConformanceTest(unittest.TestCase):
    def _stages_with_condition(self, condition, final_input: str = "w") -> dict:
        return {
            "w": {**simple_weighted(), "missingPolicy": "zero"},
            "final": {
                "id": "final",
                "phase": "finalization",
                "operator": "round",
                "inputs": [{"ref": final_input}],
                "params": {"decimalPlaces": 1},
                "condition": condition,
            },
        }

    def test_status_equals_skips(self) -> None:
        doc = policy(
            stages=self._stages_with_condition(
                {"kind": "statusEquals", "params": {"ref": "exam", "status": "approved"}}
            )
        )
        out = calculate(
            load_policy(doc),
            inputs_for(presentation=80, exam=60),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "pending")
        self.assertFalse(out.finalizable)
        self.assertEqual(out.stages[-1].decisions, ("condition statusEquals not satisfied",))

    def test_status_equals_applies(self) -> None:
        doc = policy(
            stages=self._stages_with_condition(
                {"kind": "statusEquals", "params": {"ref": "exam", "status": "approved"}}
            )
        )
        inputs = NormalizedInputs(
            subject_id="S",
            assessments={
                "presentation": AssessmentInput("presentation", True, AcademicValue.from_scalar(80, "percent"), status="approved"),
                "exam": AssessmentInput("exam", True, AcademicValue.from_scalar(60, "percent"), status="approved"),
            },
        )
        out = calculate(load_policy(doc), inputs, {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("72.0"))

    def test_score_at_least(self) -> None:
        doc = policy(
            stages=self._stages_with_condition(
                {"kind": "scoreAtLeast", "params": {"ref": "presentation", "threshold": "50"}}
            )
        )
        out = calculate(load_policy(doc), inputs_for(presentation=40, exam=60), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")

    def test_assessment_missing(self) -> None:
        doc = policy(
            stages=self._stages_with_condition(
                {"kind": "assessmentMissing", "params": {"ref": "exam"}}
            )
        )
        out = calculate(load_policy(doc), inputs_for(presentation=80, exam=None), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")


if __name__ == "__main__":
    unittest.main()
