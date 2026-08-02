"""DAG planning over policy stages.

The planner turns the stage list into a deterministic topological execution
order. The graph is a directed graph where an edge ``A -> B`` means "B reads the
output of A". Edges that read assessments are terminal leaves.

Rules:

- topological order is deterministic: lexicographic tiebreak by ``stageId``;
- cycles raise ``CycleError``;
- unknown refs (neither an assessment nor an earlier stage) raise
  ``StageReferenceError``;
- every stage must be reachable from the result stage (dead code is rejected);
- condition references (``condition.params.ref``) are first-class edges and
  participate in cycle detection, reachability and ordering.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Mapping, Optional, Sequence

from .errors import CycleError, StageReferenceError
from .models import Policy, StageSpec
from .registry import require_operator


class Plan:
    def __init__(self, policy: Policy, order: Sequence[str]) -> None:
        self.policy = policy
        self.order = order

    def iter(self) -> Sequence[str]:
        return self.order


def condition_refs(stage: StageSpec) -> Sequence[str]:
    """Refs a stage condition reads via ``condition.params.ref``.

    Every V1 condition declares its reference in ``params.ref``; those refs are
    real DAG dependencies and must participate in cycle detection, reachability
    and topological ordering exactly like input refs.
    """
    condition = stage.condition or {}
    params = condition.get("params") or {}
    ref = params.get("ref")
    if ref is not None:
        return (ref,)
    return ()


def operator_refs(stage: StageSpec) -> Sequence[str]:
    """Refs an operator declares through its params (target/source etc.).

    ``additiveBonus`` and ``replaceLowestInput`` reference entities via
    ``params`` and not only ``stage.inputs``; those references are first-class
    DAG edges and must participate in unknown-ref validation, cycle detection,
    phase ordering, reachability, topological ordering and unit propagation.
    """
    refs = []
    for op_ref in require_operator(stage.operator).references(stage):
        refs.append(op_ref.ref)
    return refs


def _references(stage: StageSpec) -> Sequence[str]:
    refs = [inp.ref for inp in stage.inputs]
    refs.extend(condition_refs(stage))
    refs.extend(operator_refs(stage))
    return refs


def _build_graph(policy: Policy) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    stage_ids = set(policy.stages.keys())
    assessment_ids = set(policy.assessments)

    predecessors: dict[str, list[str]] = {sid: [] for sid in stage_ids}
    successors: dict[str, list[str]] = defaultdict(list)

    for stage in policy.stages.values():
        for ref in _references(stage):
            if ref in stage_ids:
                predecessors[stage.id].append(ref)
                successors[ref].append(stage.id)
            elif ref not in assessment_ids:
                raise StageReferenceError(
                    f"stages[{stage.id}]: ref {ref!r} is neither a stage nor an assessment."
                )
    return predecessors, successors


def topological_order(policy: Policy) -> Sequence[str]:
    """Deterministic topo order (cycle + unknown refs only). No result checks."""
    stage_ids = set(policy.stages.keys())
    predecessors, successors = _build_graph(policy)

    # Cycle detection via DFS.
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {sid: WHITE for sid in stage_ids}
    stack: list[str] = []

    def visit(sid: str) -> None:
        color[sid] = GRAY
        stack.append(sid)
        for nxt in successors[sid]:
            if color[nxt] == GRAY:
                cycle = stack[stack.index(nxt):] + [nxt]
                raise CycleError(cycle)
            if color[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        color[sid] = BLACK

    for sid in sorted(stage_ids):
        if color[sid] == WHITE:
            visit(sid)

    # Kahn topological sort with lexicographic tiebreak.
    indegree = {sid: len(predecessors[sid]) for sid in stage_ids}
    queue = deque(sorted([sid for sid, d in indegree.items() if d == 0]))
    order: list[str] = []
    while queue:
        sid = queue.popleft()
        order.append(sid)
        for nxt in sorted(successors[sid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(stage_ids):
        # Find a concrete cycle for the error message.
        for sid in sorted(stage_ids):
            color[sid] = WHITE
        cycle_holder: list[str] = []
        local_stack: list[str] = []

        def find(sid2: str) -> bool:
            color[sid2] = GRAY
            local_stack.append(sid2)
            for nxt in successors[sid2]:
                if color[nxt] == GRAY:
                    cycle_holder.extend(local_stack[local_stack.index(nxt):] + [nxt])
                    return True
                if color[nxt] == WHITE and find(nxt):
                    return True
            local_stack.pop()
            color[sid2] = BLACK
            return False

        for sid in sorted(stage_ids):
            if color[sid] == WHITE and find(sid):
                break
        raise CycleError(cycle_holder)

    return order


def plan(policy: Policy) -> Plan:
    stage_ids = set(policy.stages.keys())
    predecessors, _ = _build_graph(policy)
    order = topological_order(policy)

    # Dead-code check: every stage must be reachable from result_stage_id.
    if policy.result_stage_id not in stage_ids:
        raise StageReferenceError(
            f"resultStageId {policy.result_stage_id!r} is not a stage."
        )

    reachable: set[str] = set()
    stack2 = [policy.result_stage_id]
    while stack2:
        sid = stack2.pop()
        if sid in reachable:
            continue
        reachable.add(sid)
        stack2.extend(predecessors[sid])

    for sid in sorted(stage_ids):
        if sid not in reachable:
            raise StageReferenceError(
                f"stage {sid!r} is unreachable from resultStageId "
                f"{policy.result_stage_id!r}; dead stages are not allowed."
            )

    return Plan(policy, tuple(order))
