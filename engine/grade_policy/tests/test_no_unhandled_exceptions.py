"""C2 fail-closed property suite: a validated policy can never surface a raw
Python error (``IndexError``/``KeyError``/``TypeError``/``ZeroDivisionError``/
``AttributeError``) at runtime.

Every valid policy is executed with randomized inputs — present and absent,
including values below/above breakpoint ranges — and the test asserts the only
errors that can escape ``calculate`` are typed ``GradePolicyError`` subclasses.
The property holds for every operator in the closed V1 catalog and for every
allowed missing policy.
"""

from __future__ import annotations

import random
import unittest

from grade_policy import (
    AcademicValue,
    AssessmentInput,
    NormalizedInputs,
    calculate,
    load_policy,
)
from grade_policy.errors import GradePolicyError

UNITS = ("percent", "points", "grade", "scalar")

MISSING_FOR_MULTI = ("fail", "zero", "excludeAndRenormalize", "pending", "notApplicable", "minimumOutput")
MISSING_FOR_SINGLE = ("fail", "zero", "pending", "notApplicable", "minimumOutput")
MISSING_FOR_REF = ("fail", "pending", "notApplicable")
MISSING_FOR_PIECEWISE = ("fail", "zero", "pending", "notApplicable")
MISSING_FOR_ROUND = ("fail", "pending", "notApplicable")


def base(assessments=("a", "b", "c"), units=None, **overrides) -> dict:
    doc = {
        "schemaVersion": "1.0.0",
        "policyId": "prop-fail-closed",
        "policyVersion": "1.0.0",
        "engineMinVersion": "0.1.0",
        "assessments": list(assessments),
        "assessmentUnits": dict(units or {}),
        "stages": {},
        "resultStageId": "r",
    }
    doc.update(overrides)
    return doc


def weighted_average_doc(missing: str) -> dict:
    params = {"minimum": {"value": "40", "unit": "percent"}} if missing == "minimumOutput" else {}
    return base(
        units={"a": "percent", "b": "percent"},
        resultStageId="w",
        stages={
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}],
                "missingPolicy": missing,
                "params": params,
            }
        },
    )


def sum_doc(missing: str) -> dict:
    params = {
        "cap": {"value": "100", "unit": "percent"},
        "floor": {"value": "0", "unit": "percent"},
        **({"minimum": {"value": "40", "unit": "percent"}} if missing == "minimumOutput" else {}),
    }
    return base(
        units={"a": "percent", "b": "percent"},
        stages={
            "r": {
                "id": "r",
                "phase": "aggregation",
                "operator": "sum",
                "inputs": [{"ref": "a"}, {"ref": "b"}],
                "missingPolicy": missing,
                "params": params,
            }
        },
    )


def unary_doc(operator: str, missing: str) -> dict:
    if operator == "round":
        params, phase, missing_set = {"decimalPlaces": 2, "mode": "halfUp"}, "finalization", MISSING_FOR_ROUND
    else:
        bound = {"cap": {"value": "100", "unit": "percent"}} if operator == "cap" else {"floor": {"value": "0", "unit": "percent"}}
        params, phase, missing_set = bound, "adjustment", MISSING_FOR_SINGLE
        if missing == "minimumOutput":
            params = {**params, "minimum": {"value": "40", "unit": "percent"}}
    if missing not in missing_set:
        return None
    return base(
        units={"a": "percent"},
        stages={
            "r": {
                "id": "r",
                "phase": phase,
                "operator": operator,
                "inputs": [{"ref": "a"}],
                "missingPolicy": missing,
                "params": params,
            }
        },
    )


def additive_bonus_doc(missing: str) -> dict:
    return base(
        units={"a": "percent", "b": "percent"},
        stages={
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [{"ref": "a", "weight": "1"}],
            },
            "r": {
                "id": "r",
                "phase": "adjustment",
                "operator": "additiveBonus",
                "inputs": [],
                "params": {"target": "w", "source": "b", "cap": {"value": "100", "unit": "percent"}},
                "missingPolicy": missing,
            },
        },
    )


def replace_lowest_doc(missing: str) -> dict:
    return base(
        units={"a": "percent", "b": "percent", "c": "percent"},
        stages={
            "w": {
                "id": "w",
                "phase": "aggregation",
                "operator": "weightedAverage",
                "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}],
            },
            "r": {
                "id": "r",
                "phase": "adjustment",
                "operator": "replaceLowestInput",
                "inputs": [],
                "params": {"target": "w", "source": "c", "tiePolicy": "replaceFirst"},
                "missingPolicy": missing,
            },
        },
    )


def piecewise_doc(missing: str, outside_range: str) -> dict:
    return base(
        units={"a": "percent"},
        stages={
            "r": {
                "id": "r",
                "phase": "conversion",
                "operator": "piecewiseLinearScale",
                "inputs": [{"ref": "a"}],
                "params": {
                    "outputUnit": "grade",
                    "outsideRange": outside_range,
                    "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                },
                "missingPolicy": missing,
            }
        },
    )


def random_inputs(rng: random.Random, refs: tuple[str, ...]) -> NormalizedInputs:
    assessments = {}
    for ref in refs:
        present = rng.random() < 0.8
        value = None
        if present:
            unit = "percent"
            value = AcademicValue.from_scalar(rng.uniform(-20, 120), unit)
        assessments[ref] = AssessmentInput(
            assessment_id=ref,
            present=present,
            value=value,
        )
    return NormalizedInputs(subject_id="S", assessments=assessments)


class NoUnhandledExceptionsTest(unittest.TestCase):
    def _assert_no_raw_errors(self, doc: dict, refs: tuple[str, ...], iterations: int = 30) -> None:
        loaded = load_policy(doc)
        rng = random.Random(hash((loaded.policy_id, refs)) % 2**32)
        for _ in range(iterations):
            inputs = random_inputs(rng, refs)
            try:
                calculate(loaded, inputs, {"subjectId": "S"})
            except GradePolicyError:
                pass

    def test_weighted_average_all_policies(self) -> None:
        for missing in MISSING_FOR_MULTI:
            self._assert_no_raw_errors(weighted_average_doc(missing), ("a", "b"))

    def test_sum_all_policies(self) -> None:
        for missing in MISSING_FOR_SINGLE:
            self._assert_no_raw_errors(sum_doc(missing), ("a", "b"))

    def test_unary_operators_all_policies(self) -> None:
        for operator in ("cap", "floor", "round"):
            for missing in ("fail", "zero", "pending", "notApplicable", "minimumOutput"):
                doc = unary_doc(operator, missing)
                if doc is None:
                    continue
                self._assert_no_raw_errors(doc, ("a",))

    def test_additive_bonus_all_policies(self) -> None:
        for missing in MISSING_FOR_REF:
            self._assert_no_raw_errors(additive_bonus_doc(missing), ("a", "b"))

    def test_replace_lowest_input_all_policies(self) -> None:
        for missing in MISSING_FOR_REF:
            self._assert_no_raw_errors(replace_lowest_doc(missing), ("a", "b", "c"))

    def test_piecewise_clamp_and_reject(self) -> None:
        for outside_range in ("clamp", "reject"):
            for missing in MISSING_FOR_PIECEWISE:
                self._assert_no_raw_errors(
                    piecewise_doc(missing, outside_range),
                    ("a",),
                    iterations=40,
                )

    def test_full_pipeline_never_raw(self) -> None:
        doc = {
            "schemaVersion": "1.0.0",
            "policyId": "prop-pipeline",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": ["EV1", "EV2", "EV3", "EV4", "EvG"],
            "assessmentUnits": {k: "percent" for k in ("EV1", "EV2", "EV3", "EV4", "EvG")},
            "resultStageId": "final-grade",
            "stages": {
                "w": {
                    "id": "w",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [
                        {"ref": "EV1", "weight": "0.25"},
                        {"ref": "EV2", "weight": "0.25"},
                        {"ref": "EV3", "weight": "0.25"},
                        {"ref": "EV4", "weight": "0.25"},
                    ],
                    "missingPolicy": "fail",
                },
                "repl": {
                    "id": "repl",
                    "phase": "adjustment",
                    "operator": "replaceLowestInput",
                    "inputs": [],
                    "params": {"target": "w", "source": "EvG", "tiePolicy": "replaceLast"},
                    "missingPolicy": "pending",
                },
                "scale": {
                    "id": "scale",
                    "phase": "conversion",
                    "operator": "piecewiseLinearScale",
                    "inputs": [{"ref": "repl"}],
                    "params": {
                        "outputUnit": "grade",
                        "outsideRange": "clamp",
                        "breakpoints": [{"x": "0", "y": "1"}, {"x": "60", "y": "4"}, {"x": "100", "y": "7"}],
                    },
                    "missingPolicy": "pending",
                },
                "final-grade": {
                    "id": "final-grade",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "scale"}],
                    "params": {"decimalPlaces": 2, "mode": "halfUp"},
                    "missingPolicy": "pending",
                },
            },
        }
        loaded = load_policy(doc)
        rng = random.Random(20260202)
        for _ in range(60):
            inputs = random_inputs(rng, ("EV1", "EV2", "EV3", "EV4", "EvG"))
            try:
                calculate(loaded, inputs, {"subjectId": "S"})
            except GradePolicyError:
                pass


if __name__ == "__main__":
    unittest.main()
