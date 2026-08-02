"""DAG planning over policy stages.

The planner turns the stage list into a deterministic topological execution
order. The graph is a directed graph where an edge ``A -> B`` means "B reads the
output of A". Edges that read assessments are terminal leaves.

Rules:

- topological order is deterministic: lexicographic tiebreak by ``stageId``;
- cycles raise ``CycleError``;
- unknown refs (neither an assessment nor an earlier stage) raise
  ``StageReferenceError``;
- every stage must be reachable from the result stage (dead code is rejected).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Mapping, Optional, Sequence

from .errors import CycleError, StageReferenceError
from .models import Policy, StageSpec


class Plan:
    def __init__(self, policy: Policy, order: Sequence[str]) -> None:
        self.policy = policy
        self.order = order

    def iter(self) -> Sequence[str]:
        return self.order


def _references(stage: StageSpec) -> Sequence[str]:
    refs = [inp.ref for inp in stage.inputs]
    condition = stage.condition or {}
    ref = condition.get("ref")
    if ref is not None:
        refs.append(ref)
    return refs


def plan(policy: Policy) -> Plan:
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
