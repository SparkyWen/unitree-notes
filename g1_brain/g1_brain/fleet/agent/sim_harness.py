"""SimRobotHarness — the headless per-robot fast/slow brain for the fleet.

It is the object a RobotAgent treats as its "core": it exposes the fleet
contract surface (capabilities, state-with-thermal, lifecycle events, admit)
while owning the local 快慢脑 stack:

    fast brain : RobotFsm + AdmissionGate (local final authority)
    slow brain : LocalPlanner (capability -> posture)
    sensing    : ThermalModel (tau-driven) over a MotionBackend
    motion     : MotionBackend (mock / elastic-PD / RL)

No camera / Realtime / codex here, so two can run side by side in sim. The
coordinator never reaches the MotionBackend except through admit() -> gate ->
planner -> posture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator

from g1_brain.fleet.agent.admission_gate import AdmissionGate
from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.agent.motion.base import MotionBackend, Posture
from g1_brain.fleet.agent.motion.mock import MockBackend
from g1_brain.fleet.agent.thermal_model import ThermalModel
from g1_brain.fleet.contracts.models import (
    AdmissionDecision, Battery, CapabilityDescriptor, CapabilityEntry, CommandEnvelope,
    CoreState, Health, RobotEvent, RobotStateMsg, SafetyStateMsg, WatchdogOk,
)
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState

# Capabilities the sim harness supports (the wire vocabulary the gate allows).
DISPATCH_CAPABILITIES = ["patrol", "idle", "stop", "sleep", "wake", "resume_task"]

# Postures that count as "moving" for the north-bound motion_state field.
_MOVING = {Posture.PATROL, Posture.WAKE}


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class SimRobotHarness:
    def __init__(self, *, robot_id: str, fsm: RobotFsm, thermal: ThermalModel,
                 backend: MotionBackend, planner: LocalPlanner, gate: AdmissionGate,
                 event_queue: "asyncio.Queue[RobotEvent]", harness_version: str = "0.1.0",
                 lowstate_dt: float = 0.1):
        self.robot_id = robot_id
        self.fsm = fsm
        self.thermal = thermal
        self.backend = backend
        self.planner = planner
        self.gate = gate
        self._events = event_queue
        self._harness_version = harness_version
        self._lowstate_dt = lowstate_dt

    # ---- factories ----
    @classmethod
    def from_mock(cls, robot_id: str, *, n_joints: int = 29,
                  initial: RobotFsmState = RobotFsmState.STANDING) -> "SimRobotHarness":
        backend = MockBackend(n_joints=n_joints)
        return cls._assemble(robot_id, backend=backend, n_joints=n_joints, initial=initial)

    @classmethod
    def from_backend(cls, robot_id: str, backend: MotionBackend, *, n_joints: int = 29,
                     initial: RobotFsmState = RobotFsmState.STANDING) -> "SimRobotHarness":
        return cls._assemble(robot_id, backend=backend, n_joints=n_joints, initial=initial)

    @classmethod
    def _assemble(cls, robot_id, *, backend, n_joints, initial) -> "SimRobotHarness":
        fsm = RobotFsm(initial=initial)
        thermal = ThermalModel(n_joints=n_joints)
        queue: "asyncio.Queue[RobotEvent]" = asyncio.Queue()
        planner = LocalPlanner(robot_id=robot_id, fsm=fsm, backend=backend,
                               emit=queue.put_nowait)
        gate = AdmissionGate(robot_id=robot_id, fsm=fsm, planner=planner,
                             supported_capabilities=set(DISPATCH_CAPABILITIES))
        return cls(robot_id=robot_id, fsm=fsm, thermal=thermal, backend=backend,
                   planner=planner, gate=gate, event_queue=queue)

    # ---- fleet "core" surface used by RobotAgent ----
    def get_capabilities(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            robot_id=self.robot_id, harness_version=self._harness_version,
            frame_id=f"{self.robot_id}/map",
            capabilities=[CapabilityEntry(name=c) for c in DISPATCH_CAPABILITIES],
        )

    def get_state(self, *, seq: int = 0) -> RobotStateMsg:
        snap = self.thermal.snapshot()
        ls = self.backend.read_lowstate()
        grav = ls.gravity_proj_z
        posture = getattr(self.backend, "last_posture", Posture.IDLE)
        motion = "moving" if posture in _MOVING else "idle"
        core = CoreState(
            safety_state=SafetyStateMsg(
                gravity_proj_z=grav,
                watchdog_ok=WatchdogOk(lowstate=True, head_frame=True,
                                       pose=grav <= -0.85),
            ),
            policy_active=(self.fsm.state == RobotFsmState.STANDING),
            battery=Battery(soc=snap.soc, temperature_c=snap.battery_temperature_c,
                            charging=snap.charging),
            health=Health(level="warning" if snap.faults else "ok", faults=snap.faults),
        )
        ext = {"g1_sim": {
            "hottest_motor_c": snap.hottest_motor_c,
            "hottest_motor_idx": snap.hottest_motor_idx,
            "mean_motor_c": snap.mean_motor_c,
            "posture": posture.value,
        }}
        return RobotStateMsg(robot_id=self.robot_id, ts=_iso_now(), seq=seq,
                             fsm_state=self.fsm.state.value, motion_state=motion,
                             core=core, extensions=ext)

    async def subscribe_events(self) -> AsyncIterator[RobotEvent]:
        while True:
            yield await self._events.get()

    def admit(self, env: CommandEnvelope) -> AdmissionDecision:
        return self.gate.admit(env)

    async def on_command(self, env: CommandEnvelope) -> AdmissionDecision:
        # The bus invokes this; the actual decision is fully synchronous/local.
        return self.gate.admit(env)

    # ---- driven by the agent loop ----
    def tick(self) -> None:
        """Advance physics + feed real joint effort into the thermal model."""
        self.backend.step()
        ls = self.backend.read_lowstate()
        self.thermal.update(tau=ls.tau_est(), dt=self._lowstate_dt)

    def inject(self, **kwargs) -> None:
        self.thermal.inject(**kwargs)

    def close(self) -> None:
        self.backend.close()
