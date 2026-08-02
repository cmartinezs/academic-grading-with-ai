"""C2 property coverage: determinism, decimal integrity and unit propagation.

Property checks implemented with stdlib only (repeated sampling), consistent
with the repository's no-extra-dependency test policy.
"""

from __future__ import annotations

import random
import unittest
from decimal import Decimal, localcontext

from grade_policy import (
    AcademicValue,
    AssessmentInput,
    NormalizedInputs,
    calculate,
    load_policy,
    outcome_id,
    policy_hash,
)
from grade_policy.decimal import WEIGHT_SUM_TOLERANCE, to_decimal
from grade_policy.serialize import serialize


def _policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "prop",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["a", "b", "c"],
        "stages": {
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [
                    {"ref": "a", "weight": "0.5"},
                    {"ref": "b", "weight": "0.3"},
                    {"ref": "c", "weight": "0.2"},
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
        "resultStageId": "final",
    }
    doc.update(overrides)
    return doc


def _inputs(scores: dict[str, float]) -> NormalizedInputs:
    return NormalizedInputs(
        subject_id="S",
        assessments={
            ref: AssessmentInput(ref, True, AcademicValue.from_scalar(score, "percent"))
            for ref, score in scores.items()
        },
    )


class DeterminismPropertyTest(unittest.TestCase):
    def test_same_inputs_same_outcome(self) -> None:
        policy = load_policy(_policy())
        inputs = _inputs({"a": 64.0, "b": 88.0, "c": 50.0})
        first = calculate(policy, inputs, {"subjectId": "S"})
        for _ in range(50):
            again = calculate(policy, inputs, {"subjectId": "S"})
            self.assertEqual(str(first.value.value), str(again.value.value))
            self.assertEqual(first.status, again.status)

    def test_outcome_id_deterministic(self) -> None:
        policy = load_policy(_policy())
        one = outcome_id("SEC", "S", policy)
        two = outcome_id("SEC", "S", policy)
        other = outcome_id("SEC", "T", policy)
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)
        self.assertTrue(one.startswith("out_"))

    def test_policy_hash_stable_across_serialization(self) -> None:
        doc = _policy()
        self.assertEqual(policy_hash(doc), policy_hash(serialize(doc) and doc))

    def test_policy_hash_sensitive_to_content(self) -> None:
        doc = _policy()
        tampered = dict(doc)
        tampered["stages"] = dict(doc["stages"])
        tampered["stages"]["final"] = {**doc["stages"]["final"], "params": {"decimalPlaces": 3, "mode": "halfUp"}}
        self.assertNotEqual(policy_hash(doc), policy_hash(tampered))


class DecimalIntegrityPropertyTest(unittest.TestCase):
    def test_no_binary_float_artifacts(self) -> None:
        value = to_decimal(0.1)
        self.assertEqual(value, Decimal("0.1"))

    def test_weighted_average_decimal_exactness(self) -> None:
        # 0.1 + 0.2 must be exactly 0.3 in the engine context, never 0.30000000000000004.
        policy = load_policy(
            {
                "schemaVersion": "1.0.0",
                "policyId": "sum10",
                "policyVersion": "1.0.0",
                "engineMinVersion": "0.1.0",
                "assessments": ["a", "b", "c"],
                "stages": {
                    "w": {
                        "id": "w",
                        "phase": "aggregation",
                        "operator": "weightedAverage",
                        "inputs": [
                            {"ref": "a", "weight": "0.1"},
                            {"ref": "b", "weight": "0.2"},
                            {"ref": "c", "weight": "0.7"},
                        ],
                    }
                },
                "resultStageId": "w",
            }
        )
        out = calculate(policy, _inputs({"a": 1, "b": 2, "c": 0}), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("0.5"))

    def test_ambient_context_does_not_affect_results(self) -> None:
        policy = load_policy(_policy())
        inputs = _inputs({"a": 33.33, "b": 66.66, "c": 50.0})
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = "ROUND_DOWN"
            inside = calculate(policy, inputs, {"subjectId": "S"})
        outside = calculate(policy, inputs, {"subjectId": "S"})
        self.assertEqual(str(inside.value.value), str(outside.value.value))

    def test_weight_sum_tolerance_boundary(self) -> None:
        self.assertLessEqual(Decimal("0.6") + Decimal("0.4"), Decimal("1") + WEIGHT_SUM_TOLERANCE)


class UnitPropagationPropertyTest(unittest.TestCase):
    def test_weighted_average_preserves_random_input_unit(self) -> None:
        for unit in ("percent", "points", "grade", "scalar"):
            doc = {
                "schemaVersion": "1.0.0",
                "policyId": "prop-units",
                "policyVersion": "1.0.0",
                "engineMinVersion": "0.1.0",
                "assessments": ["a", "b"],
                "assessmentUnits": {"a": unit, "b": unit},
                "stages": {
                    "w": {
                        "id": "w",
                        "phase": "aggregation",
                        "operator": "weightedAverage",
                        "inputs": [{"ref": "a", "weight": "0.6"}, {"ref": "b", "weight": "0.4"}],
                    },
                    "final": {
                        "id": "final",
                        "phase": "finalization",
                        "operator": "round",
                        "inputs": [{"ref": "w"}],
                        "params": {"decimalPlaces": 1, "mode": "halfUp"},
                    },
                },
                "resultStageId": "final",
            }
            loaded = load_policy(doc)
            rng = random.Random(hash(unit) % 10000)
            for _ in range(20):
                a = rng.uniform(0, 100)
                b = rng.uniform(0, 100)
                out = calculate(loaded, _inputs_unit({"a": a, "b": b}, unit), {"subjectId": "S"})
                self.assertEqual(out.value.unit, unit)
                expected = round(0.6 * a + 0.4 * b, 1)
                self.assertAlmostEqual(float(out.value.value), expected, places=8)

    def test_static_units_agree_with_runtime_across_chains(self) -> None:
        from grade_policy.units import propagate_units

        for unit in ("percent", "points", "grade", "scalar"):
            doc = {
                "schemaVersion": "1.0.0",
                "policyId": "prop-chain",
                "policyVersion": "1.0.0",
                "engineMinVersion": "0.1.0",
                "assessments": ["a"],
                "assessmentUnits": {"a": unit},
                "stages": {
                    "w": {
                        "id": "w",
                        "phase": "aggregation",
                        "operator": "weightedAverage",
                        "inputs": [{"ref": "a", "weight": "1"}],
                    },
                    "cap": {
                        "id": "cap",
                        "phase": "adjustment",
                        "operator": "cap",
                        "inputs": [{"ref": "w"}],
                        "params": {"max": "100"},
                    },
                    "final": {
                        "id": "final",
                        "phase": "finalization",
                        "operator": "round",
                        "inputs": [{"ref": "cap"}],
                        "params": {"decimalPlaces": 1},
                    },
                },
                "resultStageId": "final",
            }
            loaded = load_policy(doc)
            units = propagate_units(loaded)
            self.assertEqual(units["w"], unit)
            self.assertEqual(units["cap"], unit)
            self.assertEqual(units["final"], unit)
            out = calculate(loaded, _inputs_unit({"a": 50}, unit), {"subjectId": "S"})
            self.assertEqual(out.value.unit, units["final"])


def _inputs_unit(scores: dict[str, float], unit: str) -> NormalizedInputs:
    return NormalizedInputs(
        subject_id="S",
        assessments={
            ref: AssessmentInput(ref, True, AcademicValue.from_scalar(score, unit))
            for ref, score in scores.items()
        },
    )


class SamplingPropertyTest(unittest.TestCase):
    def test_weighted_average_matches_float_sanity(self) -> None:
        policy = load_policy(
            {
                "schemaVersion": "1.0.0",
                "policyId": "prop-avg",
                "policyVersion": "1.0.0",
                "engineMinVersion": "0.1.0",
                "assessments": ["a", "b", "c"],
                "stages": {
                    "w": {
                        "id": "w",
                        "phase": "aggregation",
                        "operator": "weightedAverage",
                        "inputs": [
                            {"ref": "a", "weight": "0.5"},
                            {"ref": "b", "weight": "0.3"},
                            {"ref": "c", "weight": "0.2"},
                        ],
                    }
                },
                "resultStageId": "w",
            }
        )
        rng = random.Random(1234)
        for _ in range(50):
            scores = {"a": rng.uniform(0, 100), "b": rng.uniform(0, 100), "c": rng.uniform(0, 100)}
            expected = (
                0.5 * scores["a"] + 0.3 * scores["b"] + 0.2 * scores["c"]
            )
            out = calculate(policy, _inputs(scores), {"subjectId": "S"})
            self.assertAlmostEqual(float(out.value.value), expected, places=8)

    def test_canonical_serialization_is_sorted_and_stable(self) -> None:
        doc = _policy()
        self.assertIn('"a"', serialize(doc))
        self.assertEqual(serialize(doc), serialize(doc))


if __name__ == "__main__":
    unittest.main()
