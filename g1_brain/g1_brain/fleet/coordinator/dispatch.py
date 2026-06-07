"""DispatchEngine — deterministic task allocation + sleep/reassign authority.

This is the *final scheduler* (doc §20.3): an LLM may propose, but the engine
decides. It matches tasks to robots by capability + health + availability and,
on an anomaly, sleeps the affected robot and reassigns its task to the best
healthy candidate. It returns plans as lists of CommandEnvelopes; issuing them
(idempotency, event log, transport) is the CommandGateway's job.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from g1_brain.fleet.coordinator.anomaly import Anomaly
from g1_brain.fleet.contracts.models import CommandEnvelope, TaskSpec


class DispatchEngine:
    def __init__(self, registry, *, issued_by: str = "coordinator",
                 clock: Callable[[], float] = time.time):
        self._registry = registry
        self._issued_by = issued_by
        self._clock = clock
        self.assignments: Dict[str, str] = {}    # task_id -> robot_id
        self.robot_task: Dict[str, str] = {}     # robot_id -> task_id
        self.tasks: Dict[str, TaskSpec] = {}
        self.needs_operator: List[str] = []

    def _cmd(self, robot_id: str, capability: str, payload: dict,
             trace_id: Optional[str]) -> CommandEnvelope:
        return CommandEnvelope.make(issued_by=self._issued_by, issued_to=robot_id,
                                    capability=capability, payload=payload,
                                    trace_id=trace_id, ttl_s=30.0, now=self._clock())

    def _candidates(self, required_caps, *, exclude=()) -> List[str]:
        scored = []
        for r in self._registry.list_robots():
            rid = r["robot_id"]
            if rid in exclude or rid in self.robot_task:
                continue
            if r["status"] != "online":
                continue
            st = r.get("state")
            if not st or st.get("fsm_state") != "STANDING":
                continue  # must be awake & available (not DORMANT/ESTOP/ACTING)
            core = st.get("core") or {}
            if (core.get("health") or {}).get("level", "ok") != "ok":
                continue
            if not set(required_caps) <= set(r.get("capabilities") or []):
                continue
            soc = (core.get("battery") or {}).get("soc", 1.0)
            scored.append((rid, soc))
        scored.sort(key=lambda x: x[1], reverse=True)  # highest SOC first
        return [rid for rid, _ in scored]

    def _bind(self, task_id: str, robot_id: str) -> None:
        self.assignments[task_id] = robot_id
        self.robot_task[robot_id] = task_id
        if task_id in self.needs_operator:
            self.needs_operator.remove(task_id)

    def assign(self, task: TaskSpec, *, trace_id: Optional[str] = None) -> Optional[CommandEnvelope]:
        self.tasks[task.task_id] = task
        cands = self._candidates(task.required_capabilities)
        if not cands:
            if task.task_id not in self.needs_operator:
                self.needs_operator.append(task.task_id)
            return None
        rid = cands[0]
        self._bind(task.task_id, rid)
        return self._cmd(rid, "patrol", {"task_id": task.task_id, "type": task.type}, trace_id)

    def release(self, robot_id: str) -> Optional[str]:
        """Free whatever task ``robot_id`` holds (keeps bookkeeping consistent).
        Returns the freed task_id, or None."""
        task_id = self.robot_task.pop(robot_id, None)
        if task_id is not None:
            self.assignments.pop(task_id, None)
        return task_id

    def reassign(self, task_id: str, *, exclude=(),
                 trace_id: Optional[str] = None) -> Optional[CommandEnvelope]:
        """Reassign a freed task to the best healthy candidate, else queue it
        for the operator. Returns the resume_task command if reassigned."""
        task = self.tasks.get(task_id)
        req = task.required_capabilities if task else []
        cands = self._candidates(req, exclude=exclude)
        if cands:
            new = cands[0]
            self._bind(task_id, new)
            return self._cmd(new, "resume_task",
                             {"task_id": task_id,
                              "type": task.type if task else "patrol"}, trace_id)
        if task_id not in self.needs_operator:
            self.needs_operator.append(task_id)
        return None

    def handle_anomaly(self, anomaly: Anomaly, *, trace_id: Optional[str] = None) -> List[CommandEnvelope]:
        rid = anomaly.robot_id
        plan: List[CommandEnvelope] = [self._cmd(rid, "sleep", {"reason": anomaly.kind}, trace_id)]
        freed = self.release(rid)
        if freed is not None:
            cmd = self.reassign(freed, exclude={rid}, trace_id=trace_id)
            if cmd is not None:
                plan.append(cmd)
        return plan

    def takeover(self, from_robot: str, to_robot: str, *,
                 trace_id: Optional[str] = None) -> List[CommandEnvelope]:
        plan: List[CommandEnvelope] = []
        task_id = self.release(from_robot)
        plan.append(self._cmd(from_robot, "idle", {}, trace_id))
        if task_id is not None:
            self._bind(task_id, to_robot)
            task = self.tasks.get(task_id)
            plan.append(self._cmd(to_robot, "resume_task",
                                  {"task_id": task_id,
                                   "type": task.type if task else "patrol"}, trace_id))
        return plan

    def sleep(self, robot_id: str, *, reason: str = "operator",
              trace_id: Optional[str] = None) -> CommandEnvelope:
        return self._cmd(robot_id, "sleep", {"reason": reason}, trace_id)

    def wake(self, robot_id: str, *, trace_id: Optional[str] = None) -> CommandEnvelope:
        return self._cmd(robot_id, "wake", {}, trace_id)
