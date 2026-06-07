"""LiveExecutor — run a fleet plan's per-robot ops against a live world, with
operator *preemption*.

This is the execution half of the command center. A FleetCommander plan (already
expanded by the sub-agents into per-robot op sequences) is handed to submit(),
which becomes the executor's *current mission*. step() advances that mission one
tick by issuing nav goals / postures to the world and watching telemetry for
arrival + the rendezvous barrier — the same op semantics the P3 scenario uses,
but factored so a *new* command can replace the running one at any moment
(latest operator intent wins). The executor keeps a single current mission;
submit() simply swaps it (bumping a generation id), so a long-lived run() loop
preempts cleanly with no task juggling.

The world only needs three thread-safe methods: telemetry(), set_nav_goal(),
set_posture() — satisfied by WorldSim (and by a fake in tests)."""
from __future__ import annotations

import asyncio
import math
from typing import Callable, Dict, List, Optional

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.coordinator.barrier import RendezvousBarrier
from g1_brain.fleet.coordinator.fleet_plan import FleetPlan, SubAgentOp


class Mission:
    """One operator command in flight: its plan, per-robot ops, and progress."""

    def __init__(self, gen: int, plan: FleetPlan, ops: Dict[str, List[SubAgentOp]]):
        self.gen = gen
        self.plan = plan
        self.ops = ops
        self.ptr: Dict[str, int] = {rid: 0 for rid in ops}
        self.events: List[str] = []
        self.complete = False
        self.barrier_fired = False
        self.min_sep = 99.0
        self.start_pose: Dict[str, tuple] = {}
        c = plan.coordination
        self._barrier = RendezvousBarrier(set(ops), point=c.point, radius=0.7)

    def all_done(self) -> bool:
        return all(self.ptr[r] >= len(self.ops[r]) for r in self.ops)

    def current_op(self, rid: str) -> Optional[str]:
        i = self.ptr.get(rid, 0)
        return self.ops[rid][i].op if i < len(self.ops[rid]) else None


class LiveExecutor:
    def __init__(self, world, *, on_event: Optional[Callable[[str], None]] = None,
                 arrive_radius: float = 0.45):
        self._world = world
        self._on_event = on_event
        self._arrive_radius = arrive_radius
        self._mission: Optional[Mission] = None
        self._gen = 0

    @property
    def mission(self) -> Optional[Mission]:
        return self._mission

    def submit(self, plan: FleetPlan, ops: Dict[str, List[SubAgentOp]]) -> Mission:
        """Make ``plan`` the current mission, preempting any running one."""
        self._gen += 1
        m = Mission(self._gen, plan, ops)
        self._mission = m
        c = plan.coordination
        self._emit(f"指挥官: {plan.summary} [{c.type}]"
                   + (f" {c.handoff_from}→{c.handoff_to}" if c.handoff_to else ""))
        return m

    def step(self) -> None:
        """Advance the current mission by one control tick."""
        m = self._mission
        if m is None or m.complete:
            return
        tel = self._world.telemetry()
        for rid in m.ops:
            t = tel.get(rid)
            if t and t["neighbors"]:
                m.min_sep = min(m.min_sep, t["neighbors"][0]["dist"])
            if m.ptr[rid] >= len(m.ops[rid]):
                continue
            op = m.ops[rid][m.ptr[rid]]
            px, py, _ = t["pose"]
            if op.op == "navigate":
                gx, gy = op.args["x"], op.args["y"]
                self._world.set_nav_goal(rid, gx, gy)
                if math.hypot(px - gx, py - gy) < self._arrive_radius:
                    m.ptr[rid] += 1
                    self._event(m, f"{rid} 到位")
            elif op.op == "await_barrier":
                m._barrier.update_position(rid, (px, py))
                if m._barrier.is_released():
                    if not m.barrier_fired:
                        m.barrier_fired = True
                        self._event(m, "会合完成 — 两机抵达集合点")
                    m.ptr[rid] += 1
            elif op.op == "patrol":
                self._world.set_posture(rid, Posture.PATROL)
                m.start_pose[rid] = (px, py)
                m.ptr[rid] += 1
                self._event(m, f"{rid} 接手巡逻")
            elif op.op == "idle":
                self._world.set_posture(rid, Posture.IDLE)
                m.ptr[rid] += 1
                self._event(m, f"{rid} 交接完毕，待命")
            elif op.op == "sleep":
                self._world.set_posture(rid, Posture.SLEEP)
                m.ptr[rid] += 1
                self._event(m, f"{rid} 休眠")
            elif op.op == "wake":
                self._world.set_posture(rid, Posture.IDLE)
                m.ptr[rid] += 1
            else:
                m.ptr[rid] += 1
        if m.all_done():
            m.complete = True
            self._event(m, "✓ 任务完成")

    async def run(self, *, tick_s: float = 0.05,
                  should_stop: Optional[Callable[[], bool]] = None) -> None:
        """Long-lived control loop: step the current mission forever (idle when
        none). A new submit() swaps the mission under it = preemption."""
        while not (should_stop and should_stop()):
            self.step()
            await asyncio.sleep(tick_s)

    def _event(self, m: Mission, msg: str) -> None:
        m.events.append(msg)
        self._emit(msg)

    def _emit(self, msg: str) -> None:
        if self._on_event:
            self._on_event(msg)
