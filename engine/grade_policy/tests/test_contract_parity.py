"""C2 contract-parity suite: the official examples and invalid cases from
``docs/implementation/C2-GRADE-POLICY-CONTRACT.md`` driven literally against the
engine.

The §2 official document is copied verbatim from the contract (its JSON block is
extracted from the markdown and loaded with no transformation). The test asserts
it validates, computes an end-to-end outcome and produces a C2 snapshot. The §13
invalid examples are driven as a rejection matrix, and the V1
``replaceLowestInput`` target restriction (§6) is exercised at both validation
and runtime.

All data is synthetic. No PII and no real snapshots.
"""

from __future__ import annotations

import json
import re
import unittest
from decimal import Decimal
from pathlib import Path

from grade_policy import (
    AcademicValue,
    AssessmentInput,
    NormalizedInputs,
    calculate,
    load_policy,
)
from grade_policy.errors import (
    GradePolicyError,
    MissingInputError,
    OutOfRangeError,
    SchemaValidationError,
    SemanticValidationError,
)

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "implementation"
    / "C2-GRADE-POLICY-CONTRACT.md"
)

LEVELS_1_TO_7 = ["1", "2", "3", "4", "5", "6", "7"]

EVG_CONDITION = {
    "kind": "levelAtLeast",
    "params": {"ref": "EvG", "level": "4", "levels": LEVELS_1_TO_7},
}


def section2_example() -> dict:
    """The literal §2 official document, copied from the contract file.

    No transformation is applied: the JSON block is extracted as-is and parsed.
    """
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    marker = "## 2. Documento de policy"
    start = text.index(marker)
    rest = text[start:]
    next_section = rest.find("\n## ", len(marker))
    section = rest if next_section == -1 else rest[:next_section]
    blocks = re.findall(r"```json\n(.*?)\n```", section, re.DOTALL)
    assert blocks, "contract §2 must contain a JSON document block"
    return json.loads(blocks[0])


def official_example(*, condition_in_params: bool = False) -> dict:
    """The §2 official document (literal), optionally with ``condition`` moved
    back into ``params`` to assert that variant is rejected."""
    doc = section2_example()
    if not condition_in_params:
        return doc
    params = {
        **doc["stages"]["evg-replacement"]["params"],
        "condition": EVG_CONDITION,
    }
    stages = dict(doc["stages"])
    stages["evg-replacement"] = {
        **doc["stages"]["evg-replacement"],
        "params": params,
    }
    stages["evg-replacement"].pop("condition", None)
    return {**doc, "stages": stages}


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
    def test_official_section2_loads_literally(self) -> None:
        """The literal §2 document (copied from the contract file) validates
        without any modification: source is PCT (percent), condition lives at
        stage.condition, EvG (level) is used only by levelAtLeast."""
        doc = section2_example()
        loaded = load_policy(doc)
        self.assertEqual(loaded.result_stage_id, "final-grade")
        replacement = doc["stages"]["evg-replacement"]
        self.assertEqual(replacement["params"]["source"], "PCT")
        self.assertNotIn("condition", replacement["params"])
        self.assertEqual(replacement["condition"]["kind"], "levelAtLeast")
        self.assertEqual(replacement["condition"]["params"]["ref"], "EvG")
        self.assertEqual(doc["assessmentUnits"]["PCT"], "percent")
        self.assertEqual(doc["assessmentUnits"]["EvG"], "level")

    def test_official_section2_calculates_final_outcome(self) -> None:
        """The literal §2 document computes an end-to-end outcome (5.56 grade):
        presentation = 78.35; replace EV3 (60) with PCT (70) -> 80.85;
        scale(80.85) = 5.56375 -> round -> 5.56."""
        doc = section2_example()
        loaded = load_policy(doc)
        out = calculate(
            loaded,
            inputs_for(
                EV1=("78.4", "percent"),
                EV2=("85", "percent"),
                EV3=("60", "percent"),
                EV4=("90", "percent"),
                PCT=("70", "percent"),
                EvG=("5", "level"),
            ),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "finalized")
        self.assertTrue(out.finalizable)
        self.assertEqual(out.value.value, Decimal("5.56"))
        self.assertEqual(out.value.unit, "grade")

    def test_official_section2_generates_c2_snapshot(self) -> None:
        """The literal §2 document produces the three C2 snapshot payloads."""
        from grade_policy.snapshot import build_c2_payloads

        doc = section2_example()
        canonical = {
            "canonical/assessments.json": {
                "assessments": [{"assessmentId": aid} for aid in ("EV1", "EV2", "EV3", "EV4", "PCT", "EvG")]
            },
            "canonical/subjects.json": {"subjects": [{"studentId": "S"}]},
            "canonical/results.json": {
                "results": [
                    {"studentId": "S", "assessmentId": aid, "score": score, "status": "Evaluada"}
                    for aid, score in {
                        "EV1": "78.4", "EV2": "85", "EV3": "60",
                        "EV4": "90", "PCT": "70", "EvG": "5",
                    }.items()
                ]
            },
        }
        payloads = build_c2_payloads("SEC", canonical, doc)
        self.assertEqual(
            set(payloads),
            {"canonical/policy.json", "canonical/outcomes.json", "canonical/traces.json"},
        )
        policy_payload = payloads["canonical/policy.json"]
        self.assertEqual(policy_payload["mode"], "grade-policy-effective")
        self.assertEqual(policy_payload["calculationAuthority"], "grade-policy-engine")
        self.assertIn("policyHash", policy_payload)
        outcomes = payloads["canonical/outcomes.json"]
        self.assertEqual(outcomes["schemaVersion"], "1.1.0")
        result = outcomes["subjectOutcomes"][0]
        self.assertEqual(result["status"], "finalized")
        self.assertEqual(result["value"], {"value": "5.56", "unit": "grade"})
        traces = payloads["canonical/traces.json"]
        self.assertEqual(traces["traceSchemaVersion"], "1.1.0")

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

        EV1-4, PCT and EvG are all percent; the gate is scoreAtLeast(EvG >= 60);
        replaceLowestInput swaps the lowest evaluation for PCT, the result is
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
                PCT=("70", "percent"),
                EvG=("70", "percent"),
            ),
            {"subjectId": "S"},
        )
        self.assertEqual(out.status, "finalized")
        # presentation = 78.35; replace EV3 (60) with PCT (70) -> 80.85;
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
        with self.assertRaises(MissingInputError):
            calculate(
                load_policy(doc),
                inputs_for(
                    EV1=("78.4", "percent"),
                    EV2=("85", "percent"),
                    EV3=("60", "percent"),
                    EV4=("90", "percent"),
                    PCT=("70", "percent"),
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


class ReplaceLowestTargetV1Test(unittest.TestCase):
    """§6 V1 target restriction of replaceLowestInput.

    The target must be an unconditional weightedAverage with missingPolicy fail
    (or none); the runtime resolves the target state before reading candidates.
    """

    def _doc(self, *, target_missing: str = None, target_condition=None) -> dict:
        target: dict = {
            "id": "w",
            "phase": "aggregation",
            "operator": "weightedAverage",
            "inputs": [
                {"ref": "a", "weight": "0.5"},
                {"ref": "b", "weight": "0.5"},
            ],
        }
        if target_missing is not None:
            target["missingPolicy"] = target_missing
        if target_condition is not None:
            target["condition"] = target_condition
        return {
            "schemaVersion": "1.0.0",
            "policyId": "rli-v1",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": ["a", "b", "c"],
            "assessmentUnits": {"a": "percent", "b": "percent", "c": "percent"},
            "resultStageId": "r",
            "stages": {
                "w": target,
                "r": {
                    "id": "r",
                    "phase": "adjustment",
                    "operator": "replaceLowestInput",
                    "inputs": [],
                    "params": {"target": "w", "source": "c", "tiePolicy": "replaceFirst"},
                },
            },
        }

    def _inputs(self, *, a="70", b="90", c="60") -> NormalizedInputs:
        return inputs_for(a=(a, "percent"), b=(b, "percent"), c=(c, "percent"))

    def test_valid_target_value(self) -> None:
        doc = self._doc()
        out = calculate(load_policy(doc), self._inputs(), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        # lowest candidate = a (70) replaced by c (60) -> 0.5*60 + 0.5*90 = 75
        self.assertEqual(out.value.value, Decimal("75"))

    def test_target_pending_rejected_by_validation(self) -> None:
        for policy_name in ("pending", "notApplicable"):
            with self.assertRaises(SemanticValidationError) as cm:
                load_policy(self._doc(target_missing=policy_name))
            messages = [msg for _, msg in cm.exception.findings]
            self.assertTrue(
                any("missingPolicy" in m and "fail" in m for m in messages),
                f"{policy_name}: {messages}",
            )

    def test_target_exclude_and_renormalize_rejected(self) -> None:
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(self._doc(target_missing="excludeAndRenormalize"))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("missingPolicy" in m and "fail" in m for m in messages),
            messages,
        )

    def test_target_zero_rejected(self) -> None:
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(self._doc(target_missing="zero"))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("missingPolicy" in m and "fail" in m for m in messages),
            messages,
        )

    def test_target_minimum_output_rejected(self) -> None:
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(self._doc(target_missing="minimumOutput"))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("missingPolicy" in m and "fail" in m for m in messages),
            messages,
        )

    def test_target_skipped_condition_rejected(self) -> None:
        condition = {
            "kind": "scoreAtLeast",
            "params": {"ref": "a", "threshold": {"value": "50", "unit": "percent"}},
        }
        with self.assertRaises(SemanticValidationError) as cm:
            load_policy(self._doc(target_condition=condition))
        messages = [msg for _, msg in cm.exception.findings]
        self.assertTrue(
            any("must not declare a condition" in m for m in messages),
            messages,
        )

    def test_target_pending_runtime_propagates_typed_error(self) -> None:
        """Runtime guard: a target not in state=value fails closed with a typed
        error before candidates are read (constructed bypassing the validator to
        exercise the guard)."""
        from grade_policy.models import (
            AssessmentInput,
            InputRef,
            NormalizedInputs,
            Policy,
            StageSpec,
        )

        policy = Policy(
            policy_id="rli-runtime",
            policy_version="1.0.0",
            engine_min_version="0.1.0",
            schema_version="1.0.0",
            assessments=("a", "b", "c"),
            stages={
                "w": StageSpec(
                    id="w",
                    phase="aggregation",
                    operator="weightedAverage",
                    inputs=(
                        InputRef("a", Decimal("0.5")),
                        InputRef("b", Decimal("0.5")),
                    ),
                    missing_policy="pending",
                ),
                "r": StageSpec(
                    id="r",
                    phase="adjustment",
                    operator="replaceLowestInput",
                    inputs=(),
                    params={"target": "w", "source": "c", "tiePolicy": "replaceFirst"},
                    missing_policy="fail",
                ),
            },
            result_stage_id="r",
            assessment_units={"a": "percent", "b": "percent", "c": "percent"},
        )
        inputs = NormalizedInputs(
            subject_id="S",
            assessments={
                "a": AssessmentInput("a", True, AcademicValue.from_scalar(70, "percent")),
                "c": AssessmentInput("c", True, AcademicValue.from_scalar(60, "percent")),
            },
        )
        with self.assertRaises(MissingInputError) as cm:
            calculate(policy, inputs, {"subjectId": "S"})
        self.assertIn("state=value", str(cm.exception))

    def test_weights_used_equal_target_weights(self) -> None:
        doc = self._doc()
        out = calculate(load_policy(doc), self._inputs(), {"subjectId": "S"})
        ev = next(e for e in out.stages if e.stage.id == "r")
        weights = ev.operator_data["weights"]
        self.assertEqual(weights, {"a": "0.5", "b": "0.5"})


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
