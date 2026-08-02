"""C2 typed-stage-state tests: value/missing/pending/notApplicable/skippedCondition
propagation, downstream reasoning, deterministic traces and the 1.1.0 schemas."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

from grade_policy import (
    AcademicValue,
    AssessmentInput,
    NormalizedInputs,
    calculate,
    load_policy,
    outcomes_document,
    traces_document,
)
from grade_policy.schemas import select_schema
from grade_policy.errors import MissingInputError


def policy(**overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "states",
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


def state_by(outcome) -> dict[str, str]:
    return {ev.stage.id: ev.state for ev in outcome.stages}


class PropagationTest(unittest.TestCase):
    def test_pending_propagation_with_downstream_reason(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}],
                           missingPolicy="pending"),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 1}, missingPolicy="pending"),
            },
        )
        out = calculate(load_policy(doc), inputs_for(a=(90, "percent"), b=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(out.status, "pending")
        self.assertEqual(state_by(out), {"w": "pending", "final": "pending"})
        final_ev = out.stages[1]
        self.assertEqual(len(final_ev.missing_decisions), 1)
        md = final_ev.missing_decisions[0]
        self.assertEqual(md.ref, "w")
        self.assertIn("missing", md.reason.lower())

    def test_not_applicable_propagation(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "1"}], missingPolicy="notApplicable"),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 1}, missingPolicy="pending"),
            },
        )
        out = calculate(load_policy(doc), inputs_for(a=(None, "percent")), {"subjectId": "S"})
        self.assertEqual(state_by(out), {"w": "notApplicable", "final": "pending"})
        final_ev = out.stages[1]
        md = final_ev.missing_decisions[0]
        self.assertEqual(md.policy, "pending")
        self.assertIn("notApplicable", md.reason)

    def test_condition_skip_propagation(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "1"}]),
                "final": stage(
                    "final", "finalization", "round", [{"ref": "w"}],
                    params={"decimalPlaces": 1}, missingPolicy="pending",
                    condition={"kind": "scoreAtLeast", "params": {"ref": "w", "threshold": {"value": "50", "unit": "percent"}}},
                ),
            },
        )
        out = calculate(load_policy(doc), inputs_for(a=(40, "percent")), {"subjectId": "S"})
        self.assertEqual(out.state, "skippedCondition")
        self.assertEqual(out.status, "pending")
        self.assertEqual(state_by(out), {"w": "value", "final": "skippedCondition"})
        self.assertFalse(out.stages[1].applied)

    def test_fail_downstream_still_raises(self) -> None:
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "1"}], missingPolicy="pending"),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 1}, missingPolicy="fail"),
            },
        )
        with self.assertRaises(MissingInputError):
            calculate(load_policy(doc), inputs_for(a=(None, "percent")), {"subjectId": "S"})

    def test_missing_reason_for_assessment(self) -> None:
        doc = policy(resultStageId="w",
                     stages={"w": stage("w", "aggregation", "weightedAverage",
                                        [{"ref": "a", "weight": "1"}], missingPolicy="pending")})
        out = calculate(load_policy(doc), inputs_for(a=(None, "percent")), {"subjectId": "S"})
        md = out.stages[0].missing_decisions[0]
        self.assertEqual(md.ref, "a")
        self.assertEqual(md.reason, "not present")


class DeterministicTraceTest(unittest.TestCase):
    def _doc(self) -> dict:
        return policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.6"}, {"ref": "b", "weight": "0.4"}],
                           missingPolicy="zero"),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 2}),
            },
        )

    def test_same_inputs_same_trace(self) -> None:
        loaded = load_policy(self._doc())
        inputs = inputs_for(a=(80, "percent"), b=(None, "percent"))
        first = calculate(loaded, inputs, {"subjectId": "S"})
        second = calculate(loaded, inputs, {"subjectId": "S"})
        self.assertEqual(traces_document(loaded, {"S": first}), traces_document(loaded, {"S": second}))
        self.assertEqual(outcomes_document({"S": first}), outcomes_document({"S": second}))


class TraceSchemaTest(unittest.TestCase):
    def _build(self):
        doc = policy(
            resultStageId="final",
            stages={
                "w": stage("w", "aggregation", "weightedAverage",
                           [{"ref": "a", "weight": "0.6"}, {"ref": "b", "weight": "0.4"}],
                           missingPolicy="zero"),
                "final": stage("final", "finalization", "round",
                               [{"ref": "w"}], params={"decimalPlaces": 2}),
            },
        )
        loaded = load_policy(doc)
        return loaded, calculate(loaded, inputs_for(a=(80, "percent"), b=(None, "percent")), {"subjectId": "S"})

    def _validate(self, schema: dict, instance: dict) -> list[str]:
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(schema)
        return [
            f"{'.'.join(str(e.absolute_path) or '$')}: {e.message}"
            for e in sorted(validator.iter_errors(instance), key=lambda e: str(e.absolute_path))
        ]

    def test_trace_document_matches_1_1_0_schema(self) -> None:
        loaded, out = self._build()
        doc = traces_document(loaded, {"S": out})
        self.assertEqual(doc["traceSchemaVersion"], "1.1.0")
        errors = self._validate(select_schema("traces", "1.1.0"), doc)
        self.assertEqual(errors, [])

    def test_outcomes_document_matches_1_1_0_schema(self) -> None:
        _, out = self._build()
        doc = outcomes_document({"S": out})
        self.assertEqual(doc["schemaVersion"], "1.1.0")
        errors = self._validate(select_schema("outcomes", "1.1.0"), doc)
        self.assertEqual(errors, [])
        self.assertTrue(doc["subjectOutcomes"][0]["finalizable"])

    def test_trace_records_state_and_missing_decisions(self) -> None:
        loaded, out = self._build()
        doc = traces_document(loaded, {"S": out})
        w_stage = next(s for s in doc["subjectTraces"][0]["stages"] if s["stageId"] == "w")
        self.assertEqual(w_stage["state"], "value")
        self.assertTrue(w_stage["missingDecisions"])
        md = w_stage["missingDecisions"][0]
        self.assertEqual(md["ref"], "b")
        self.assertIn("policy", md)
        self.assertIn("resultingState", md)
        self.assertEqual(md["resultingState"], "value")
        self.assertIn("originalWeight", md)


if __name__ == "__main__":
    unittest.main()
