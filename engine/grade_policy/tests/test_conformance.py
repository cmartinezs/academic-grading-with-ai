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


def piecewise_stage(stage_id: str = "scale", output_unit: str = "grade",
                    breakpoints=None, outside_range: str = "clamp", **extra) -> dict:
    return {
        "id": stage_id,
        "phase": "conversion",
        "operator": "piecewiseLinearScale",
        "inputs": [{"ref": "presentation"}],
        "params": {
            "outputUnit": output_unit,
            "outsideRange": outside_range,
            "breakpoints": breakpoints or [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
        },
        **extra,
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
        # piecewiseLinearScale emits level; weightedAverage cannot read a level.
        doc = policy(
            resultStageId="w",
            stages={
                "scale1": piecewise_stage(output_unit="level", breakpoints=[
                    {"x": "0", "y": "1"}, {"x": "7", "y": "1"}]),
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "scale1", "weight": "1"}],
                },
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_piecewise_output_unit_missing_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "presentation"}],
                    "params": {
                        "outsideRange": "clamp",
                        "breakpoints": [{"x": "0", "y": "1"}, {"x": "50", "y": "4"}],
                    },
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_piecewise_outside_range_missing_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "presentation"}],
                    "params": {
                        "outputUnit": "grade",
                        "breakpoints": [{"x": "0", "y": "1"}, {"x": "50", "y": "4"}],
                    },
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_duplicate_breakpoint_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "presentation"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": "clamp",
                        "breakpoints": [{"x": "50", "y": "1"}, {"x": "50", "y": "4"}],
                    },
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_unsorted_breakpoint_rejected(self) -> None:
        doc = policy(
            resultStageId="scale",
            stages={
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "presentation"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": "clamp",
                        "breakpoints": [{"x": "60", "y": "4"}, {"x": "0", "y": "1"}],
                    },
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_weighted_average_requires_weights(self) -> None:
        doc = policy(
            resultStageId="w",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "presentation"}, {"ref": "exam"}],
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_weight_on_sum_rejected(self) -> None:
        doc = policy(
            resultStageId="s",
            stages={
                "s": {
                    "id": "s",
                    "phase": "aggregation",
                    "operator": "sum",
                    "inputs": [{"ref": "presentation", "weight": "0.5"}, {"ref": "exam", "weight": "0.5"}],
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_weights_not_one_rejected_at_validation(self) -> None:
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
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_negative_weight_rejected(self) -> None:
        doc = policy(
            resultStageId="w",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [
                        {"ref": "presentation", "weight": "1.5"},
                        {"ref": "exam", "weight": "-0.5"},
                    ],
                }
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

    def test_weighted_average_weights_not_one_runtime_guard(self) -> None:
        # Static validation catches it, but the runtime guard must stay typed.
        doc = policy(
            resultStageId="w",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [
                        {"ref": "presentation", "weight": "0.6"},
                        {"ref": "exam", "weight": "0.3"},
                    ],
                }
            }
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_sum(self) -> None:
        doc = policy(
            resultStageId="s",
            stages={"s": {"id": "s", "phase": "aggregation", "operator": "sum",
                          "inputs": [{"ref": "presentation"}, {"ref": "exam"}]}}
        )
        out = calculate(load_policy(doc), inputs_for(presentation=10, exam=20), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("30"))
        self.assertEqual(out.value.unit, "percent")

    def test_sum_typed_cap_and_floor(self) -> None:
        doc = policy(
            resultStageId="s",
            stages={
                "s": {
                    "id": "s",
                    "phase": "aggregation",
                    "operator": "sum",
                    "inputs": [{"ref": "presentation"}, {"ref": "exam"}],
                    "params": {
                        "floor": {"value": "10", "unit": "percent"},
                        "cap": {"value": "50", "unit": "percent"},
                    },
                }
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=100, exam=100), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("50"))
        self.assertEqual(out.value.unit, "percent")

    def test_piecewise_linear_scale(self) -> None:
        doc = policy(resultStageId="scale", stages={"scale": piecewise_stage()})
        out = calculate(load_policy(doc), inputs_for(presentation=90), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("6.25"))
        self.assertEqual(out.value.unit, "grade")

    def test_piecewise_linear_scale_exact_breakpoint(self) -> None:
        doc = policy(resultStageId="scale", stages={"scale": piecewise_stage()})
        out = calculate(load_policy(doc), inputs_for(presentation=60), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("4"))

    def test_piecewise_linear_scale_clamps_low(self) -> None:
        doc = policy(resultStageId="scale", stages={"scale": piecewise_stage()})
        out = calculate(load_policy(doc), inputs_for(presentation=-10), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("1"))

    def test_piecewise_linear_scale_clamps_high(self) -> None:
        doc = policy(resultStageId="scale", stages={"scale": piecewise_stage()})
        out = calculate(load_policy(doc), inputs_for(presentation=120), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("7"))

    def test_additive_bonus(self) -> None:
        doc = policy(
            assessments=["presentation", "bonus"],
            resultStageId="b",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "presentation", "weight": "1"}],
                },
                "b": {
                    "id": "b",
                    "phase": "adjustment",
                    "operator": "additiveBonus",
                    "inputs": [],
                    "params": {
                        "target": "w",
                        "source": "bonus",
                        "cap": {"value": "100", "unit": "percent"},
                    },
                },
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=80, bonus=5), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("85"))

    def test_additive_bonus_cap_applied(self) -> None:
        doc = policy(
            assessments=["presentation", "bonus"],
            resultStageId="b",
            stages={
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "presentation", "weight": "1"}],
                },
                "b": {
                    "id": "b",
                    "phase": "adjustment",
                    "operator": "additiveBonus",
                    "inputs": [],
                    "params": {
                        "target": "w",
                        "source": "bonus",
                        "cap": {"value": "100", "unit": "percent"},
                    },
                },
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=98, bonus=5), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("100"))

    def test_replace_lowest_input(self) -> None:
        doc = policy(
            assessments=["presentation", "exam", "replacement"],
            resultStageId="r",
            stages={
                "w": simple_weighted(),
                "r": {
                    "id": "r",
                    "phase": "adjustment",
                    "operator": "replaceLowestInput",
                    "inputs": [],
                    "params": {"target": "w", "source": "replacement", "tiePolicy": "replaceFirst"},
                },
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=70, exam=90, replacement=60), {"subjectId": "S"})
        # lowest candidate = presentation (70) replaced by 60 -> 0.6*60 + 0.4*90 = 72
        self.assertEqual(out.value.value, Decimal("72"))

    def test_cap(self) -> None:
        doc = policy(
            resultStageId="c",
            stages={
                "c": {"id": "c", "phase": "adjustment", "operator": "cap",
                      "inputs": [{"ref": "presentation"}],
                      "params": {"cap": {"value": "100", "unit": "percent"}}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation=120), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("100"))

    def test_floor(self) -> None:
        doc = policy(
            resultStageId="f",
            stages={
                "f": {"id": "f", "phase": "adjustment", "operator": "floor",
                      "inputs": [{"ref": "presentation"}],
                      "params": {"floor": {"value": "0", "unit": "percent"}}}
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

    def test_round_quantum(self) -> None:
        doc = policy(
            resultStageId="r",
            stages={
                "r": {"id": "r", "phase": "finalization", "operator": "round",
                      "inputs": [{"ref": "presentation"}],
                      "params": {"quantum": "0.1", "mode": "halfUp"}}
            }
        )
        out = calculate(load_policy(doc), inputs_for(presentation="5.325"), {"subjectId": "S"})
        self.assertEqual(str(out.value.value), "5.3")


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
                {"kind": "scoreAtLeast", "params": {"ref": "presentation", "threshold": {"value": "50", "unit": "percent"}}}
            )
        )
        out = calculate(load_policy(doc), inputs_for(presentation=40, exam=60), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")

    def test_score_below(self) -> None:
        doc = policy(
            stages=self._stages_with_condition(
                {"kind": "scoreBelow", "params": {"ref": "presentation", "threshold": {"value": "50", "unit": "percent"}}}
            )
        )
        out = calculate(load_policy(doc), inputs_for(presentation=40, exam=60), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")

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
