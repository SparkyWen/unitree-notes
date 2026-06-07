"""RobotSubAgent — one per robot. Turns its assignment + the shared
coordination contract into a validated op sequence. OpenAI path optional;
deterministic fallback keeps it usable/testable with no key."""
from __future__ import annotations

import logging
from typing import List

from g1_brain.fleet.coordinator.fleet_plan import (
    Coordination, RobotAssignment, SubAgentOp)

log = logging.getLogger(__name__)
_VALID = {"navigate", "await_barrier", "patrol", "idle", "sleep", "wake"}


class RobotSubAgent:
    def __init__(self, robot_id: str, llm=None):
        self.robot_id = robot_id
        self._llm = llm

    def plan_ops(self, assignment: RobotAssignment,
                 coordination: Coordination) -> List[SubAgentOp]:
        if self._llm is not None:
            try:
                raw = self._llm.plan_robot(self.robot_id, assignment.model_dump(),
                                           coordination.model_dump())
                ops = [SubAgentOp.model_validate(o) for o in (raw or [])]
                ops = [o for o in ops if o.op in _VALID]
                if ops:
                    return ops
            except Exception:  # noqa: BLE001
                log.warning("llm subagent failed; deterministic fallback", exc_info=True)
        return self._deterministic(assignment, coordination)

    def _deterministic(self, assignment: RobotAssignment,
                       coordination: Coordination) -> List[SubAgentOp]:
        ops: List[SubAgentOp] = []
        if assignment.goal is not None:
            ops.append(SubAgentOp(op="navigate",
                                  args={"x": assignment.goal[0], "y": assignment.goal[1]}))
        if coordination.type in ("rendezvous", "relay"):
            ops.append(SubAgentOp(op="await_barrier",
                                  args={"point": list(coordination.point or (0.0, 0.0))}))
        if coordination.type == "relay":
            if self.robot_id == coordination.handoff_to:
                ops.append(SubAgentOp(op=coordination.handoff_task or "patrol"))
            elif self.robot_id == coordination.handoff_from:
                ops.append(SubAgentOp(op="idle"))
        return ops
