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
import time
from typing import Callable, Dict, List, Optional

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.coordinator.barrier import RendezvousBarrier
from g1_brain.fleet.coordinator.fleet_plan import FleetPlan, SubAgentOp

_FACE_DONE = 0.2       # rad: "facing the target" once heading error is within this
_FACE_TIMEOUT = 8.0    # s: stop turning toward a face target after this long
_ARMS_SETTLE = 1.5     # s: stand still this long before raising arms, so the
                       # robot is settled — raising arms mid-stride topples it


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
        self.op_t0: Dict[str, tuple] = {}     # rid -> (op_index, clock when it began)
        self.fired: set = set()               # (rid, op_index) one-shot guards
        c = plan.coordination
        self._barrier = RendezvousBarrier(set(ops), point=c.point, radius=0.7)

    def all_done(self) -> bool:
        return all(self.ptr[r] >= len(self.ops[r]) for r in self.ops)

    def current_op(self, rid: str) -> Optional[str]:
        i = self.ptr.get(rid, 0)
        return self.ops[rid][i].op if i < len(self.ops[rid]) else None


class LiveExecutor:
    def __init__(self, world, *, on_event: Optional[Callable[[str], None]] = None,
                 arrive_radius: float = 0.45, clock: Optional[Callable[[], float]] = None):
        self._world = world
        self._on_event = on_event
        self._arrive_radius = arrive_radius
        self._clock = clock or time.monotonic
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
        now = self._clock()
        tel = self._world.telemetry()
        for rid in m.ops:
            t = tel.get(rid)
            if t and t["neighbors"]:
                m.min_sep = min(m.min_sep, t["neighbors"][0]["dist"])
            i = m.ptr[rid]
            if i >= len(m.ops[rid]):
                continue
            # stamp when this op first begins (timed ops + one-shot triggers)
            started = m.op_t0.get(rid, (None, 0.0))[0] != i
            if started:
                m.op_t0[rid] = (i, now)
            elapsed = now - m.op_t0[rid][1]
            op = m.ops[rid][i]
            if hasattr(self._world, "set_peer_avoid"):
                self._world.set_peer_avoid(rid, op.op not in ("await_barrier", "face"))
            px, py, yaw = t["pose"]
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
            elif op.op == "circle":
                if started:
                    self._world.set_circle(rid, op.args.get("dir", "ccw"))
                if elapsed >= float(op.args.get("seconds", 10.0)):
                    self._world.set_idle(rid)
                    m.ptr[rid] += 1
                    self._event(m, f"{rid} 绕圈结束")
            elif op.op == "face":
                tx, ty = op.args["x"], op.args["y"]
                self._world.set_face(rid, tx, ty)
                desired = math.atan2(ty - py, tx - px)
                err = math.atan2(math.sin(yaw - desired), math.cos(yaw - desired))
                if abs(err) < _FACE_DONE or elapsed > _FACE_TIMEOUT:
                    self._world.set_idle(rid)
                    m.ptr[rid] += 1
                    self._event(m, f"{rid} 面向对方")
            elif op.op == "arms_up":
                # stand still and settle, THEN raise (raising mid-stride topples)
                if started:
                    self._world.set_idle(rid)
                hold = float(op.args.get("seconds", 2.5))
                key = (rid, i)
                if elapsed >= _ARMS_SETTLE and key not in m.fired:
                    self._world.set_arms_up(rid, True)   # queue gesture ONCE
                    m.fired.add(key)
                if elapsed >= _ARMS_SETTLE + hold:
                    m.ptr[rid] += 1
                    self._event(m, f"{rid} 抬起双手")
            elif op.op == "hold":
                if started:
                    self._world.set_idle(rid)
                if elapsed >= float(op.args.get("seconds", 2.0)):
                    m.ptr[rid] += 1
                    self._event(m, f"{rid} 就位")
            elif op.op == "patrol":
                self._world.set_posture(rid, Posture.PATROL)
                m.start_pose[rid] = (px, py)
                m.ptr[rid] += 1
                self._event(m, f"{rid} 接手巡逻")
            elif op.op == "idle":
                self._world.set_posture(rid, Posture.IDLE)
                m.ptr[rid] += 1
                self._event(m, f"{rid} 待命")
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
