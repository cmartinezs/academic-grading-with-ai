"""C2 contract-parity suite: the official examples and invalid cases from
``docs/implementation/C2-GRADE-POLICY-CONTRACT.md`` driven verbatim against the
engine.

The §2 official document is a *shape* illustration. Two internal tensions with
other, clearer parts of the contract are resolved here (documented inline):

- ``condition`` is placed at ``stage.condition``, not inside ``params`` (§2
  Reglas del documento and §7 both define conditions as a first-class
  stage-level gate; a per-operator ``params.condition`` would duplicate that
  concept and break the single-location rule).
- The example's ``replaceLowestInput`` source ``EvG`` is ``level`` while the
  target candidates are ``percent``. §13 forbids mixing known units in a
  homogeneous stage, and §6 requires the operator to preserve the target unit;
  the engine therefore rejects the mix at validation (fail-closed) instead of
  failing with a runtime unit error.

All data is synthetic. No PII and no real snapshots.
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
    GradePolicyError,
    OutOfRangeError,
    SchemaValidationError,
    SemanticValidationError,
)

LEVELS_1_TO_7 = ["1", "2", "3", "4", "5", "6", "7"]

EVG_CONDITION = {
    "kind": "levelAtLeast",
    "params": {"ref": "EvG", "level": "4", "levels": LEVELS_1_TO_7},
}


def official_example(*, condition_in_params: bool = False) -> dict:
    """The §2 official document, with ``condition`` resolved to stage level."""
    params = {"target": "presentation-score", "source": "EvG", "tiePolicy": "replaceFirst"}
    stage_extra: dict = {"condition": EVG_CONDITION}
    if condition_in_params:
        params = {**params, "condition": EVG_CONDITION}
        stage_extra = {}
    return {
        "schemaVersion": "1.0.0",
        "policyId": "policy_fpy_2026_v1",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["EV1", "EV2", "EV3", "EV4", "PCT", "EvG"],
        "assessmentUnits": {
            "EV1": "percent", "EV2": "percent", "EV3": "percent",
            "EV4": "percent", "PCT": "percent", "EvG": "level",
        },
        "resultStageId": "final-grade",
        "stages": {
            "presentation-score": {
                "id": "presentation-score",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [
                    {"ref": "EV1", "weight": "0.25"},
                    {"ref": "EV2", "weight": "0.25"},
                    {"ref": "EV3", "weight": "0.25"},
                    {"ref": "EV4", "weight": "0.25"},
                ],
                "params": {},
                "missingPolicy": "fail",
            },
            "evg-replacement": {
                "id": "evg-replacement",
                "phase": "adjustment",
                "operator": "replaceLowestInput",
                "inputs": [],
                "params": params,
                "missingPolicy": "fail",
                **stage_extra,
            },
            "final-scale": {
                "id": "final-scale",
                "phase": "conversion",
                "operator": "piecewiseLinearScale",
                "inputs": [{"ref": "evg-replacement"}],
                "params": {
                    "outputUnit": "grade",
                    "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    "outsideRange": "clamp",
                },
                "missingPolicy": "fail",
            },
            "final-grade": {
                "id": "final-grade",
                "phase": "finalization",
                "operator": "round",
                "inputs": [{"ref": "final-scale"}],
                "params": {"decimalPlaces": 2, "mode": "halfUp"},
                "missingPolicy": "fail",
            },
        },
    }


def inputs_for(**values) -> NormalizedInputs:
    assessments = {}
    for ref, (value, unit) in values.items():
        assessments[ref] = AssessmentInput(
            assessment_id=ref,
            present=value is not None,
            value=AcademicValue.from_scalar(value, unit) if value is not None else None,
        )
    return NormalizedInputs(subject_id="S", assessments=assessments)


class OfficialExampleTest(unittest.TestCase):
    def test_official_example_rejects_unit_mix_only(self) -> None:
        """The §2 example loads once the level/percent source mix is rejected.

        The only findings must be the source-vs-candidate unit mixing; the
        ``levels`` catalog and stage-level condition are both accepted.
        """
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(official_example())
        locations = {loc for loc, _ in cm.exception.findings}
        self.assertEqual(locations, {"stages[evg-replacement]"})
        for _, msg in cm.exception.findings:
            self.assertIn("incompatible with candidate", msg)

    def test_condition_in_params_rejected(self) -> None:
        """Conditions belong at stage.condition; params stay operator-owned."""
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(official_example(condition_in_params=True))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("'condition' was unexpected" in msg for msg in messages),
            messages,
        )

    def test_coherent_pipeline_runs_end_to_end(self) -> None:
        """The official pipeline with a unit-coherent source produces 5.56.

        EV1-4 and EvG are all percent; the gate is scoreAtLeast(EvG >= 60);
        replaceLowestInput swaps the lowest evaluation for EvG, the result is
        piecewise-scaled to a grade and rounded.
        """
        doc = official_example()
        doc["assessmentUnits"] = {k: "percent" for k in doc["assessmentUnits"]}
        doc["stages"]["evg-replacement"]["condition"] = {
            "kind": "scoreAtLeast",
            "params": {"ref": "EvG", "threshold": {"value": "60", "unit": "percent"}},
        }
        out = calculate(
            load_policy(doc),
            inputs_for(
                EV1=("78.4", "percent"),
                EV2=("85", "percent"),
                EV3=("60", "percent"),
                EV4=("90", "percent"),
                EvG=("70", "percent"),
            ),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "finalized")
        # presentation = 78.35; replace EV3 (60) with 70 -> 80.85;
        # scale(80.85) = 4 + (80.85-60)/40*3 = 5.56375 -> 5.56
        self.assertEqual(out.value.value, Decimal("5.56"))
        self.assertEqual(out.value.unit, "grade")
        self.assertTrue(out.finalizable)

    def test_coherent_pipeline_gate_skips_fails_closed(self) -> None:
        doc = official_example()
        doc["assessmentUnits"] = {k: "percent" for k in doc["assessmentUnits"]}
        doc["stages"]["evg-replacement"]["condition"] = {
            "kind": "scoreAtLeast",
            "params": {"ref": "EvG", "threshold": {"value": "60", "unit": "percent"}},
        }
        # The gate skips evg-replacement; the downstream stages use
        # missingPolicy=fail, so the outcome fails closed (typed error).
        from grade_policy.errors import MissingInputError

        with self.assertRaises(MissingInputError):
            calculate(
                load_policy(doc),
                inputs_for(
                    EV1=("78.4", "percent"),
                    EV2=("85", "percent"),
                    EV3=("60", "percent"),
                    EV4=("90", "percent"),
                    EvG=("50", "percent"),
                ),
                {"subjectId": "S"},
            )


class LevelAtLeastTest(unittest.TestCase):
    def _doc(self, condition) -> dict:
        return {
            "schemaVersion": "1.0.0",
            "policyId": "lvl",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": ["ev1", "EvG"],
            "assessmentUnits": {"ev1": "percent", "EvG": "level"},
            "resultStageId": "final",
            "stages": {
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "ev1", "weight": "1"}],
                },
                "final": {
                    "id": "final",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "w"}],
                    "params": {"decimalPlaces": 2, "mode": "halfUp"},
                    "condition": condition,
                },
            },
        }

    def test_levels_catalog_applies(self) -> None:
        out = calculate(
            load_policy(self._doc(EVG_CONDITION)),
            inputs_for(ev1=("80", "percent"), EvG=("5", "level")),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("80.00"))

    def test_levels_catalog_skips_below_target(self) -> None:
        out = calculate(
            load_policy(self._doc(EVG_CONDITION)),
            inputs_for(ev1=("80", "percent"), EvG=("3", "level")),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "pending")
        self.assertFalse(out.finalizable)

    def test_typed_level_with_catalog(self) -> None:
        condition = {
            "kind": "levelAtLeast",
            "params": {"ref": "EvG", "level": {"value": "4", "unit": "level"}, "levels": LEVELS_1_TO_7},
        }
        out = calculate(
            load_policy(self._doc(condition)),
            inputs_for(ev1=("80", "percent"), EvG=("6", "level")),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "finalized")

    def test_level_outside_catalog_rejected(self) -> None:
        condition = {
            "kind": "levelAtLeast",
            "params": {"ref": "EvG", "level": "8", "levels": LEVELS_1_TO_7},
        }
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(self._doc(condition))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(any("not within the declared levels" in m for m in messages), messages)

    def test_levels_optional(self) -> None:
        condition = {
            "kind": "levelAtLeast",
            "params": {"ref": "EvG", "level": "4"},
        }
        loaded = load_policy(self._doc(condition))
        out = calculate(loaded, inputs_for(ev1=("80", "percent"), EvG=("4", "level")), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")


class InvalidExamplesTest(unittest.TestCase):
    """§13 invalid examples, driven as rejection matrix."""

    def _policy(self, stages, assessments=("a", "b"), units=None) -> dict:
        return {
            "schemaVersion": "1.0.0",
            "policyId": "invalid",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": list(assessments),
            "assessmentUnits": dict(units or {}),
            "resultStageId": "r",
            "stages": stages,
        }

    def assert_rejected(self, doc) -> None:
        with self.assertRaises(GradePolicyError):
            load_policy(doc)

    def test_additive_bonus_unit_incompatible(self) -> None:
        doc = self._policy(
            units={"a": "percent", "b": "points"},
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "1"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "additiveBonus",
                      "inputs": [], "params": {"target": "w", "source": "b"}},
            },
        )
        self.assert_rejected(doc)

    def test_additive_bonus_missing_source_rejected(self) -> None:
        doc = self._policy(
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "1"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "additiveBonus",
                      "inputs": [], "params": {"target": "w", "source": "ghost"}},
            },
        )
        self.assert_rejected(doc)

    def test_cap_wrong_unit_rejected(self) -> None:
        doc = self._policy(
            units={"a": "percent"},
            stages={
                "r": {"id": "r", "phase": "adjustment", "operator": "cap",
                      "inputs": [{"ref": "a"}], "params": {"cap": {"value": "4", "unit": "grade"}}},
            },
        )
        self.assert_rejected(doc)

    def test_sum_cap_wrong_unit_rejected(self) -> None:
        doc = self._policy(
            units={"a": "percent", "b": "percent"},
            stages={
                "r": {"id": "r", "phase": "aggregation", "operator": "sum",
                      "inputs": [{"ref": "a"}, {"ref": "b"}],
                      "params": {"cap": {"value": "4", "unit": "grade"}}},
            },
        )
        self.assert_rejected(doc)

    def test_zero_on_round_rejected(self) -> None:
        doc = self._policy(
            stages={
                "r": {"id": "r", "phase": "finalization", "operator": "round",
                      "inputs": [{"ref": "a"}], "params": {"decimalPlaces": 1},
                      "missingPolicy": "zero"},
            },
        )
        self.assert_rejected(doc)

    def test_minimum_output_on_round_rejected(self) -> None:
        doc = self._policy(
            stages={
                "r": {"id": "r", "phase": "finalization", "operator": "round",
                      "inputs": [{"ref": "a"}], "params": {"decimalPlaces": 1},
                      "missingPolicy": "minimumOutput"},
            },
        )
        self.assert_rejected(doc)

    def test_zero_on_additive_bonus_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "b"),
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "1"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "additiveBonus",
                      "inputs": [], "params": {"target": "w", "source": "b"},
                      "missingPolicy": "zero"},
            },
        )
        self.assert_rejected(doc)

    def test_minimum_output_on_additive_bonus_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "b"),
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "1"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "additiveBonus",
                      "inputs": [], "params": {"target": "w", "source": "b"},
                      "missingPolicy": "minimumOutput"},
            },
        )
        self.assert_rejected(doc)

    def test_zero_on_replace_lowest_input_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "b", "c"),
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "replaceLowestInput",
                      "inputs": [], "params": {"target": "w", "source": "c", "tiePolicy": "replaceFirst"},
                      "missingPolicy": "zero"},
            },
        )
        self.assert_rejected(doc)

    def test_minimum_output_on_replace_lowest_input_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "b", "c"),
            stages={
                "w": {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "replaceLowestInput",
                      "inputs": [], "params": {"target": "w", "source": "c", "tiePolicy": "replaceFirst"},
                      "missingPolicy": "minimumOutput"},
            },
        )
        self.assert_rejected(doc)

    def test_exclude_renormalize_matrix_rejected(self) -> None:
        cases = {
            "round": {"id": "r", "phase": "finalization", "operator": "round",
                      "inputs": [{"ref": "a"}], "params": {"decimalPlaces": 1}},
            "additiveBonus": {"id": "r", "phase": "adjustment", "operator": "additiveBonus",
                              "inputs": [], "params": {"target": "w", "source": "b"}},
            "replaceLowestInput": {"id": "r", "phase": "adjustment", "operator": "replaceLowestInput",
                                   "inputs": [], "params": {"target": "w", "source": "c", "tiePolicy": "replaceFirst"}},
            "piecewiseLinearScale": {"id": "r", "phase": "conversion", "operator": "piecewiseLinearScale",
                                     "inputs": [{"ref": "a"}],
                                     "params": {"outputUnit": "grade", "outsideRange": "clamp",
                                                "breakpoints": [{"x": "0", "y": "1"}, {"x": "50", "y": "4"}]}},
        }
        for operator, stage in cases.items():
            deps = {}
            if operator in ("additiveBonus", "replaceLowestInput"):
                deps["w"] = {"id": "w", "phase": "aggregation", "operator": "weightedAverage",
                             "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]}
            doc = self._policy(
                assessments=("a", "b", "c"),
                stages={**deps, "r": {**stage, "missingPolicy": "excludeAndRenormalize"}},
            )
            self.assert_rejected(doc)

    def test_mixed_declared_units_rejected(self) -> None:
        doc = self._policy(
            units={"a": "percent", "b": "points"},
            stages={
                "r": {"id": "r", "phase": "aggregation", "operator": "weightedAverage",
                      "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}]},
            },
        )
        self.assert_rejected(doc)

    def test_duplicate_assessment_id_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "a"),
            stages={"r": {"id": "r", "phase": "aggregation", "operator": "sum",
                          "inputs": [{"ref": "a"}]}},
        )
        with self.assertRaises(SchemaValidationError):
            load_policy(doc)

    def test_piecewise_without_breakpoints_rejected(self) -> None:
        doc = self._policy(
            stages={
                "r": {"id": "r", "phase": "conversion", "operator": "piecewiseLinearScale",
                      "inputs": [{"ref": "a"}],
                      "params": {"outputUnit": "grade", "outsideRange": "clamp"}},
            },
        )
        self.assert_rejected(doc)

    def test_replace_lowest_input_target_not_weighted_rejected(self) -> None:
        doc = self._policy(
            assessments=("a", "b", "c"),
            stages={
                "s": {"id": "s", "phase": "aggregation", "operator": "sum",
                      "inputs": [{"ref": "a"}, {"ref": "b"}]},
                "r": {"id": "r", "phase": "adjustment", "operator": "replaceLowestInput",
                      "inputs": [], "params": {"target": "s", "source": "c", "tiePolicy": "replaceFirst"}},
            },
        )
        self.assert_rejected(doc)


class PiecewiseRejectTest(unittest.TestCase):
    def test_reject_outside_range_raises_typed_error(self) -> None:
        doc = {
            "schemaVersion": "1.0.0",
            "policyId": "reject",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": ["a"],
            "resultStageId": "scale",
            "stages": {
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "a"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": "reject",
                        "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    },
                }
            },
        }
        from grade_policy.errors import OutOfRangeError

        with self.assertRaises(OutOfRangeError):
            calculate(load_policy(doc), inputs_for(a=("120", "percent")), {"subjectId": "S"})


if __name__ == "__main__":
    unittest.main()
