"""C2 self-check runner: runs the grade_policy unittest suite plus a synthetic E2E.

Returns the unittest result code (0 = all green).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))


def run_unittests() -> int:
    suite = unittest.defaultTestLoader.discover("grade_policy.tests", top_level_dir=".")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_e2e() -> None:
    from grade_policy import load_policy, calculate
    from grade_policy.models import AcademicValue, AssessmentInput, NormalizedInputs

    policy = load_policy(
        {
            "schemaVersion": "1.0.0",
            "policyId": "e2e-policy",
            "policyVersion": "1.0.0",
            "engineMinVersion": "0.1.0",
            "assessments": ["a", "b"],
            "stages": {
                "weighted": {
                    "id": "weighted",
                    "phase": "aggregation",
                    "operator": "weightedAverage",
                    "inputs": [{"ref": "a", "weight": "0.5"}, {"ref": "b", "weight": "0.5"}],
                },
                "rounded": {
                    "id": "rounded",
                    "phase": "finalization",
                    "operator": "round",
                    "inputs": [{"ref": "weighted"}],
                    "params": {"decimalPlaces": 2, "mode": "halfUp"},
                },
            },
            "resultStageId": "rounded",
        }
    )
    inputs = NormalizedInputs(
        subject_id="SUBJ-E2E",
        assessments={
            "a": AssessmentInput("a", True, AcademicValue.from_scalar(64, "percent")),
            "b": AssessmentInput("b", True, AcademicValue.from_scalar(88, "percent")),
        },
    )
    outcome = calculate(policy, inputs, context={"subjectId": "SUBJ-E2E"})
    assert outcome.status == "finalized", outcome.status
    assert str(outcome.value.value) == "76.00", outcome.value
    print(f"E2E OK: SUBJ-E2E -> {outcome.value.to_dict()}")


def main() -> int:
    code = run_unittests()
    run_e2e()
    return code


if __name__ == "__main__":
    sys.exit(main())
