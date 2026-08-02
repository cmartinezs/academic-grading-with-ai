"""C2 operator-spec introspection: every closed-V1 operator declares its
contract (arity, weight rule, referenced refs, phase, units, missing policies,
closed params schema) exactly as the contract matrix in §6 requires."""

from __future__ import annotations

import unittest

from grade_policy.registry import available_conditions, available_operators, operator_spec
from grade_policy.operators import OperatorReference

WEIGHT_RULES = ("required", "forbidden", "optional")

CONTRACT_WEIGHT_RULES = {
    "weightedAverage": "required",
    "sum": "forbidden",
    "piecewiseLinearScale": "forbidden",
    "additiveBonus": "forbidden",
    "replaceLowestInput": "forbidden",
    "cap": "forbidden",
    "floor": "forbidden",
    "round": "forbidden",
}

CONTRACT_REFERENCED_REFS = {
    "additiveBonus": (
        ("target", "stage", True),
        ("source", "either", True),
    ),
    "replaceLowestInput": (
        ("target", "stage", True),
        ("source", "either", True),
    ),
}

CONTRACT_ARITY = {
    "piecewiseLinearScale": (1, 1),
    "cap": (1, 1),
    "floor": (1, 1),
    "round": (1, 1),
    "additiveBonus": (0, 0),
    "replaceLowestInput": (0, 0),
}


def _walk_subschemas(node: dict) -> list[dict]:
    """Flatten object schemas in a params schema tree."""
    subs: list[dict] = []
    if not isinstance(node, dict):
        return subs
    if node.get("type") == "object":
        subs.append(node)
    for key in ("properties", "anyOf", "oneOf", "items", "additionalProperties"):
        child = node.get(key)
        if isinstance(child, dict):
            subs.extend(_walk_subschemas(child))
        elif isinstance(child, list):
            for item in child:
                subs.extend(_walk_subschemas(item))
    return subs


class OperatorCatalogTest(unittest.TestCase):
    def test_closed_catalog_has_exactly_eight_operators(self) -> None:
        self.assertEqual(
            set(available_operators()),
            {"weightedAverage", "sum", "piecewiseLinearScale", "additiveBonus",
             "replaceLowestInput", "cap", "floor", "round"},
        )

    def test_conditions_closed_catalog(self) -> None:
        self.assertEqual(
            set(available_conditions()),
            {"statusEquals", "levelAtLeast", "assessmentPresent", "assessmentMissing",
             "scoreAtLeast", "scoreBelow"},
        )

    def test_every_spec_is_well_formed(self) -> None:
        for name in available_operators():
            spec = operator_spec(name)
            self.assertEqual(spec.name, name)
            self.assertTrue(spec.version)
            self.assertTrue(spec.min_engine_version)
            self.assertTrue(spec.allowed_phases)
            self.assertTrue(spec.accepted_input_units)
            self.assertTrue(spec.allowed_missing_policies)
            self.assertTrue(spec.description)
            self.assertIn(spec.weight_rule, WEIGHT_RULES, name)
            self.assertGreaterEqual(spec.min_inputs, 0, name)
            if spec.max_inputs is not None:
                self.assertGreaterEqual(spec.max_inputs, spec.min_inputs, name)
            for sub in _walk_subschemas(spec.params_schema):
                self.assertIs(
                    sub.get("additionalProperties"),
                    False,
                    f"{name}: params schema must close additional properties: {sub}",
                )

    def test_weight_rules_match_contract(self) -> None:
        for name, expected in CONTRACT_WEIGHT_RULES.items():
            self.assertEqual(operator_spec(name).weight_rule, expected, name)

    def test_arity_bounds_match_contract(self) -> None:
        for name, (lo, hi) in CONTRACT_ARITY.items():
            spec = operator_spec(name)
            self.assertEqual((spec.min_inputs, spec.max_inputs), (lo, hi), name)

    def test_referenced_refs_match_contract(self) -> None:
        for name, expected in CONTRACT_REFERENCED_REFS.items():
            spec = operator_spec(name)
            stage = None
            if name == "additiveBonus":
                from grade_policy.models import StageSpec

                stage = StageSpec(
                    id="x",
                    phase="adjustment",
                    operator=name,
                    inputs=(),
                    params={"target": "t", "source": "s"},
                    missing_policy="fail",
                    condition=None,
                )
            else:
                from grade_policy.models import StageSpec

                stage = StageSpec(
                    id="x",
                    phase="adjustment",
                    operator=name,
                    inputs=(),
                    params={"target": "t", "source": "s", "tiePolicy": "replaceFirst"},
                    missing_policy="fail",
                    condition=None,
                )
            refs = spec.references(stage)
            got = tuple((r.ref, r.role, r.expected_kind, r.required) for r in refs)
            expected_full = tuple((ref, role, kind, req) for ref, role, kind, req in (
                ("t", "target", "stage", True),
                ("s", "source", "either", True),
            ))
            self.assertEqual(got, expected_full, name)

    def test_condition_ref_kinds_are_closed(self) -> None:
        from grade_policy.conditions import CONDITION_REF_KINDS

        self.assertEqual(
            CONDITION_REF_KINDS,
            {
                "statusEquals": "assessment",
                "levelAtLeast": "either",
                "assessmentPresent": "assessment",
                "assessmentMissing": "assessment",
                "scoreAtLeast": "either",
                "scoreBelow": "either",
            },
        )


if __name__ == "__main__":
    unittest.main()
