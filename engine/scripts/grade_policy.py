#!/usr/bin/env python3
"""grade-policy — C2 grade policy engine CLI (validate/calculate/explain/registry/test).

Exit codes:
    0 success
    1 usage / invalid state (bad input file, missing policy)
    2 gate failure (schema, semantic, privacy) — fail-closed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from grade_policy import (  # noqa: E402
    available_conditions,
    available_operators,
    available_rounding_modes,
    calculate,
    load_policy,
)
from grade_policy.errors import GradePolicyError, UsageError  # noqa: E402
from grade_policy.models import AcademicValue, AssessmentInput, NormalizedInputs  # noqa: E402
from grade_policy.snapshot import load_policy_document  # noqa: E402
from grade_policy.decimal import decimal_str  # noqa: E402


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _redact(text: str) -> str:
    return re.sub(
        r"\b(?:\d{1,2}\.\d{3}\.\d{2,3}|\d{6,8})-[\dKk]\b", "[RUT]", text
    )


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(description="C2 grade policy engine (v0.1.0).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Validate a policy document (schema + semantics).")
    p_validate.add_argument("policy", help="Path to the policy JSON document.")

    p_calc = sub.add_parser("calculate", help="Run the engine over an inputs file.")
    p_calc.add_argument("policy", help="Path to the policy JSON document.")
    p_calc.add_argument("--inputs", required=True, help="Path to the inputs JSON file.")
    p_calc.add_argument("--section", help="Section id used in outcomeId derivation.")

    p_explain = sub.add_parser("explain", help="Human-readable per-stage trace.")
    p_explain.add_argument("policy", help="Path to the policy JSON document.")
    p_explain.add_argument("--inputs", required=True, help="Path to the inputs JSON file.")
    p_explain.add_argument("--section", help="Section id used in outcomeId derivation.")

    sub.add_parser("registry", help="List the closed V1 operator/condition/unit catalog.")

    sub.add_parser("test", help="Run the C2 conformance and property suite.")

    return parser


def load_inputs(path: Path) -> dict[str, NormalizedInputs]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UsageError(f"Inputs file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError(f"Inputs file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("subjects"), dict):
        raise UsageError(
            "Inputs file must be an object with a 'subjects' mapping of subjectId -> "
            "{assessmentId -> {present, value, unit, status}}."
        )
    subjects: dict[str, NormalizedInputs] = {}
    for subject_id, raw in payload["subjects"].items():
        assessments = {}
        for ref, entry in raw.items():
            assessments[ref] = AssessmentInput(
                assessment_id=str(ref),
                present=bool(entry.get("present", False)),
                value=AcademicValue.from_scalar(entry["value"], entry.get("unit", "percent"))
                if entry.get("present") and entry.get("value") is not None
                else None,
                status=entry.get("status"),
            )
        subjects[str(subject_id)] = NormalizedInputs(subject_id=str(subject_id), assessments=assessments)
    return subjects


def cmd_validate(args) -> int:
    raw = load_policy_document(Path(args.policy))
    policy = load_policy(raw)
    print(f"Valid: {policy.policy_id} v{policy.policy_version} "
          f"(schema {policy.schema_version}, engine min {policy.engine_min_version}).")
    print(f"Stages: {', '.join(policy.ordered_stages())} -> result {policy.result_stage_id}")
    return 0


def cmd_calculate(args) -> int:
    raw = load_policy_document(Path(args.policy))
    policy = load_policy(raw)
    inputs = load_inputs(Path(args.inputs))
    section = args.section
    outcomes = []
    for subject_id in sorted(inputs):
        outcome = calculate(
            policy, inputs[subject_id], context={"sectionId": section, "subjectId": subject_id}
        )
        row = {"subjectId": outcome.subject_id, "status": outcome.status, "finalizable": outcome.finalizable}
        if outcome.value is not None:
            row["value"] = outcome.value.to_dict()
        outcomes.append(row)
    print(json.dumps({"schemaVersion": "1.0.0", "subjectOutcomes": outcomes}, indent=2))
    return 0


def cmd_explain(args) -> int:
    raw = load_policy_document(Path(args.policy))
    policy = load_policy(raw)
    inputs = load_inputs(Path(args.inputs))
    for subject_id in sorted(inputs):
        outcome = calculate(
            policy, inputs[subject_id], context={"sectionId": args.section, "subjectId": subject_id}
        )
        print(f"== {subject_id} -> {outcome.status}"
              + (f" = {decimal_str(outcome.value.value)} {outcome.value.unit}" if outcome.value else ""))
        for ev in outcome.stages:
            applied = "applied" if ev.applied else "skipped"
            output = f" => {decimal_str(ev.output.value)} {ev.output.unit}" if ev.output else ""
            print(f"   {ev.stage.id:20s} [{ev.stage.phase}] {ev.stage.operator} {applied}{output}")
            for decision in ev.decisions:
                print(f"     - {decision}")
            if ev.warnings:
                print(f"     warnings: {', '.join(ev.warnings)}")
    return 0


def cmd_registry(args) -> int:
    print("Engine version: 0.1.0")
    print("Operators:", ", ".join(available_operators()))
    print("Conditions:", ", ".join(available_conditions()))
    print("Rounding modes:", ", ".join(available_rounding_modes()))
    print("Units: percent, points, grade, scalar, level")
    print("Phases: normalization, aggregation, adjustment, conversion, finalization")
    return 0


def cmd_test(args) -> int:
    test_runner = ROOT / "engine" / "scripts" / "grade_policy_test.py"
    if not test_runner.is_file():
        print("C2 test runner not found; run the test milestone first.", file=sys.stderr)
        return 1
    import runpy

    code = runpy.run_path(str(test_runner), run_name="__main__")["main"]()
    return int(code)


COMMANDS = {
    "validate": cmd_validate,
    "calculate": cmd_calculate,
    "explain": cmd_explain,
    "registry": cmd_registry,
    "test": cmd_test,
}


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except UsageError as exc:
        print(f"Usage error: {_redact(str(exc))}", file=sys.stderr)
        return 1
    except GradePolicyError as exc:
        print(f"Gate failed (fail-closed): {_redact(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
