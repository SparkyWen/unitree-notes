"""DispatchController — orchestrates the autonomous + human-command loop.

It is the only place that turns *perception* (AnomalyDetector) and *operator
intent* (CoordinatorAgent) into *deterministic* dispatch (DispatchEngine) and
*audited* commands (CommandGateway). The LLM never bypasses this; it only feeds
validated StructuredOps in.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from g1_brain.fleet.clock import iso_now as _iso_now
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.contracts.models import (
    EventType, Mission, RobotEvent, TaskSpec,
)


class DispatchController:
    def __init__(self, *, registry, detector, engine, gateway, event_log,
                 lease=None, agent: Optional[CoordinatorAgent] = None,
                 inject_hook: Optional[Callable[..., None]] = None):
        self.registry = registry
        self.detector = detector
        self.engine = engine
        self.gateway = gateway
        self.event_log = event_log
        self.lease = lease
        self.agent = agent or CoordinatorAgent()
        self._inject_hook = inject_hook
        self._trace_seq = 0
        self.last_anomalies: list = []
        # Serialize state mutations: the background tick and HTTP handlers both
        # mutate engine bookkeeping across await points (single event loop, but
        # interleavable). One lock keeps assignments/needs_operator consistent.
        self._lock = asyncio.Lock()

    def _next_trace(self, tag: str) -> str:
        self._trace_seq += 1
        return f"trace-{tag}-{self._trace_seq}"

    def _emit(self, robot_id: str, etype: EventType, payload: dict, trace_id: str) -> None:
        self.event_log.append(RobotEvent.make(robot_id=robot_id, type=etype,
                                              ts=_iso_now(), payload=payload,
                                              trace_id=trace_id))

    async def _issue_plan(self, plan, *, anomaly_robot: Optional[str], trace: str) -> None:
        for cmd in plan:
            if cmd.capability == "resume_task":
                self._emit(cmd.issued_to, EventType.TASK_REASSIGNED,
                           {"task_id": cmd.payload.get("task_id"),
                            "from": anomaly_robot, "to": cmd.issued_to}, trace)
            await self.gateway.issue(cmd)

    async def tick(self) -> list:
        """One autonomous cycle: perceive anomalies + lease expiry, then act."""
        async with self._lock:
            anomalies = self.detector.scan(self.registry)
            self.last_anomalies = anomalies
            for a in anomalies:
                trace = self._next_trace(a.kind)
                self._emit(a.robot_id, EventType.ANOMALY_DETECTED,
                           {"kind": a.kind, "severity": a.severity, "evidence": a.evidence},
                           trace)
                plan = self.engine.handle_anomaly(a, trace_id=trace)
                await self._issue_plan(plan, anomaly_robot=a.robot_id, trace=trace)
            if self.lease is not None:
                for exp in self.lease.tick():
                    trace = self._next_trace("lease")
                    self._emit(exp.robot_id, EventType.LEASE_EXPIRED,
                               {"lease_id": exp.lease_id}, trace)
                    await self.gateway.issue(
                        self.engine.sleep(exp.robot_id, reason="lease_expired", trace_id=trace))
                    freed = self.engine.release(exp.robot_id)
                    if freed is not None:
                        cmd = self.engine.reassign(freed, exclude={exp.robot_id}, trace_id=trace)
                        if cmd is not None:
                            self._emit(cmd.issued_to, EventType.TASK_REASSIGNED,
                                       {"task_id": freed, "from": exp.robot_id,
                                        "to": cmd.issued_to}, trace)
                            await self.gateway.issue(cmd)
            return anomalies

    async def dispatch_mission(self, mission: Mission) -> dict:
        async with self._lock:
            for task in mission.tasks:
                cmd = self.engine.assign(task, trace_id=mission.mission_id)
                if cmd is not None:
                    await self.gateway.issue(cmd)
            return self.snapshot()

    def inject(self, robot_id: str, **kwargs) -> None:
        if self._inject_hook is not None:
            self._inject_hook(robot_id, **kwargs)

    async def run_op(self, op: StructuredOp) -> dict:
        ok, reason = self.agent.validate(op, self.registry)
        if not ok:
            return {"ok": False, "reason": reason}
        async with self._lock:
            if op.kind == "status":
                return {"ok": True, **self.snapshot()}
            if op.kind == "sleep":
                rid = op.args["robot"]
                trace = self._next_trace("op-sleep")
                await self.gateway.issue(
                    self.engine.sleep(rid, reason="operator", trace_id=trace))
                # release the robot's task so it is not stuck on a dormant robot
                freed = self.engine.release(rid)
                if freed is not None:
                    cmd = self.engine.reassign(freed, exclude={rid}, trace_id=trace)
                    if cmd is not None:
                        self._emit(cmd.issued_to, EventType.TASK_REASSIGNED,
                                   {"task_id": freed, "from": rid, "to": cmd.issued_to}, trace)
                        await self.gateway.issue(cmd)
            elif op.kind == "wake":
                await self.gateway.issue(self.engine.wake(op.args["robot"]))
            elif op.kind == "takeover":
                trace = self._next_trace("takeover")
                plan = self.engine.takeover(op.args["from"], op.args["to"], trace_id=trace)
                await self._issue_plan(plan, anomaly_robot=op.args["from"], trace=trace)
            elif op.kind == "dispatch":
                task = TaskSpec(task_id=f"task-{op.args.get('task', 'patrol')}",
                                type="patrol", required_capabilities=["patrol"])
                cmd = self.engine.assign(task, trace_id=self._next_trace("dispatch"))
                if cmd is not None:
                    await self.gateway.issue(cmd)
            else:
                return {"ok": False, "reason": f"unsupported op {op.kind!r}"}
            return {"ok": True, **self.snapshot()}

    def snapshot(self) -> dict:
        leases = self.lease.active() if self.lease is not None else []
        return {
            "assignments": dict(self.engine.assignments),
            "needs_operator": list(self.engine.needs_operator),
            "anomalies": [{"robot_id": a.robot_id, "kind": a.kind,
                           "severity": a.severity, "evidence": a.evidence,
                           "ts": a.ts} for a in self.last_anomalies],
            "leases": [{"lease_id": r.lease_id, "robot_id": r.robot_id,
                        "expiry": r.expiry} for r in leases],
        }
