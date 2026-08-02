"""C2 DAG tests: condition references are first-class graph edges.

Covers dependency-through-condition ordering, phase-order rejection, unknown
condition refs, cycles created (partially or only) by conditions, and the
lexicographic-contrary topological ordering rule.
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
from grade_policy.errors import CycleError, SemanticValidationError, StageReferenceError
from grade_policy.graph import condition_refs, plan


def policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "dag-conditions",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": ["x"],
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
            score is not None,
            AcademicValue.from_scalar(score, "percent") if score is not None else None,
        )
        for ref, score in values.items()
    }
    return NormalizedInputs(subject_id="S", assessments=assessments)


class ConditionRefTest(unittest.TestCase):
    def test_condition_refs_read_params_ref(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage", [{"ref": "x", "weight": "1"}]),
                "final": stage(
                    "final",
                    "finalization",
                    "round",
                    [{"ref": "w"}],
                    params={"decimalPlaces": 1},
                    condition={"kind": "scoreAtLeast", "params": {"ref": "w", "threshold": "50"}},
                ),
            },
        )
        loaded = load_policy(doc)
        final = loaded.stages["final"]
        self.assertEqual(condition_refs(final), ("w",))

    def test_condition_depends_on_previous_stage(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage", [{"ref": "x", "weight": "1"}]),
                "final": stage(
                    "final",
                    "finalization",
                    "round",
                    [{"ref": "w"}],
                    params={"decimalPlaces": 1},
                    condition={"kind": "scoreAtLeast", "params": {"ref": "w", "threshold": "50"}},
                ),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(x=60), {"subjectId": "S"})
        self.assertEqual(out.status, "finalized")
        self.assertEqual(out.value.value, Decimal("60.0"))

    def test_condition_depends_on_previous_stage_skips(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage", [{"ref": "x", "weight": "1"}]),
                "final": stage(
                    "final",
                    "finalization",
                    "round",
                    [{"ref": "w"}],
                    params={"decimalPlaces": 1},
                    condition={"kind": "scoreAtLeast", "params": {"ref": "w", "threshold": "50"}},
                ),
            },
        )
        loaded = load_policy(doc)
        out = calculate(loaded, inputs_for(x=40), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")
        self.assertEqual(out.state, "skippedCondition")

    def test_condition_depends_on_later_phase_rejected(self) -> None:
        doc = policy(
            resultStageId="norm",
            stages={
                "agg": stage("agg", "aggregation", "sum", [{"ref": "x"}]),
                "norm": stage(
                    "norm",
                    "normalization",
                    "sum",
                    [{"ref": "agg"}],
                    condition={"kind": "scoreAtLeast", "params": {"ref": "agg", "threshold": "50"}},
                ),
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_input_depends_on_later_phase_rejected(self) -> None:
        doc = policy(
            resultStageId="norm",
            stages={
                "agg": stage("agg", "aggregation", "sum", [{"ref": "x"}]),
                "norm": stage("norm", "normalization", "sum", [{"ref": "agg"}]),
            },
        )
        with self.assertRaises(SemanticValidationError):
            load_policy(doc)

    def test_unknown_condition_ref_rejected(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "final": stage(
                    "final",
                    "finalization",
                    "round",
                    [{"ref": "x"}],
                    params={"decimalPlaces": 1},
                    condition={"kind": "scoreAtLeast", "params": {"ref": "ghost", "threshold": "50"}},
                ),
            },
        )
        with self.assertRaises(StageReferenceError):
            load_policy(doc)

    def test_cycle_inputs_and_condition_rejected(self) -> None:
        doc = policy(
            resultStageId="a",
            stages={
                "a": stage(
                    "a",
                    "aggregation",
                    "sum",
                    [{"ref": "b"}],
                    condition={"kind": "assessmentPresent", "params": {"ref": "b"}},
                ),
                "b": stage("b", "aggregation", "sum", [{"ref": "a"}]),
            },
        )
        with self.assertRaises(CycleError):
            load_policy(doc)

    def test_cycle_only_conditions_rejected(self) -> None:
        doc = policy(
            resultStageId="a",
            stages={
                "a": stage(
                    "a",
                    "aggregation",
                    "sum",
                    [{"ref": "x"}],
                    condition={"kind": "scoreAtLeast", "params": {"ref": "b", "threshold": "50"}},
                ),
                "b": stage(
                    "b",
                    "aggregation",
                    "sum",
                    [{"ref": "x"}],
                    condition={"kind": "scoreAtLeast", "params": {"ref": "a", "threshold": "50"}},
                ),
            },
        )
        with self.assertRaises(CycleError):
            load_policy(doc)

    def test_lexicographic_order_contrary_to_dependency(self) -> None:
        # "a" depends on "b"; lexicographically "a" < "b", but the dependency
        # forces "b" to be evaluated first.
        doc = policy(
            resultStageId="a",
            stages={
                "a": stage("a", "aggregation", "sum", [{"ref": "b"}]),
                "b": stage("b", "aggregation", "sum", [{"ref": "x"}]),
            },
        )
        loaded = load_policy(doc)
        self.assertEqual(plan(loaded).order, ("b", "a"))
        out = calculate(loaded, inputs_for(x=3), {"subjectId": "S"})
        self.assertEqual(out.value.value, Decimal("3"))

    def test_dead_stage_reachable_only_through_condition_rejected(self) -> None:
        # A stage referenced only by a condition of a reachable stage is
        # reachable and therefore valid.
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage", [{"ref": "x", "weight": "1"}]),
                "final": stage(
                    "final",
                    "finalization",
                    "round",
                    [{"ref": "x"}],
                    params={"decimalPlaces": 1},
                    condition={"kind": "scoreAtLeast", "params": {"ref": "w", "threshold": "50"}},
                ),
            },
        )
        loaded = load_policy(doc)
        self.assertIn("w", loaded.stages)
        self.assertEqual(plan(loaded).order, ("w", "final"))


if __name__ == "__main__":
    unittest.main()
