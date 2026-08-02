"""Static unit propagation through the stage DAG.

``propagate_units`` computes the output unit of every stage using each
operator's ``resolve_output_unit`` and the units declared for assessments in
the policy. A stage whose output unit cannot be decided statically (because an
assessment has no declared unit) yields ``None``: the engine never claims a
static unit that could differ from the runtime one.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .graph import topological_order
from .models import Policy
from .registry import require_operator


def propagate_units(policy: Policy) -> Mapping[str, Optional[str]]:
    """Map refs (assessments + stage ids) to their statically-known unit.

    Assessment refs use the policy-declared unit (or ``None``). Stage refs use
    ``OperatorSpec.resolve_output_unit`` evaluated in topological order, so a
    chain ``percent -> weightedAverage -> cap`` resolves to ``percent`` for both
    stages.
    """
    units: dict[str, Optional[str]] = {
        aid: policy.assessment_unit(aid) for aid in policy.assessments
    }
    order = topological_order(policy)
    for sid in order:
        stage = policy.stages[sid]
        spec = require_operator(stage.operator)
        input_units = {inp.ref: units.get(inp.ref) for inp in stage.inputs}
        units[sid] = spec.resolve_output_unit(stage, input_units)
    return units
