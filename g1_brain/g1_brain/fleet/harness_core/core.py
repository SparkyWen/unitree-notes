"""HarnessCore — thin read-only facade over existing per-robot subsystems.

Incremental wrap: it does NOT own or restart anything. It is constructed with
already-built objects (RobotFsm, SceneStateBus, RobotStateBus, EventSink) and
exposes the fleet contract surface. No control path exists here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from g1_brain.safety.state_machine import RobotFsm
from g1_brain.scene_state.fusion import SceneStateBus, RobotStateBus
from g1_brain.scene_state.types import SceneState
from g1_brain.fleet.contracts.capability_export import build_capability_descriptor
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, CoreState, SafetyStateMsg,
    WatchdogOk, Battery, Health, AdmissionDecision,
)
from g1_brain.fleet.harness_core.event_fanout import EventSink


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class HarnessCore:
    def __init__(self, *, robot_id: str, fsm: RobotFsm,
                 scene_bus: SceneStateBus, robot_bus: RobotStateBus,
                 event_sink: EventSink, harness_version: str = "0.1.0",
                 lowstate_max_age_s: float = 0.5, head_max_age_s: float = 2.0,
                 admission_gate=None, thermal=None):
        self.robot_id = robot_id
        self._fsm = fsm
        self._scene = scene_bus
        self._robot = robot_bus
        self._sink = event_sink
        self._harness_version = harness_version
        self._lowstate_max_age = lowstate_max_age_s
        self._head_max_age = head_max_age_s
        # Optional: wiring these promotes the read-only facade to command-capable
        # + thermal-aware. Left None for the pure read-only slice.
        self._admission_gate = admission_gate
        self._thermal = thermal

    def get_capabilities(self) -> CapabilityDescriptor:
        return build_capability_descriptor(
            robot_id=self.robot_id, harness_version=self._harness_version,
            frame_id=f"{self.robot_id}/map",
        )

    def get_state(self, *, seq: int = 0) -> RobotStateMsg:
        body = self._robot.snapshot()
        lowstate_ok = self._robot.lowstate_age_s() <= self._lowstate_max_age
        head_ok = self._scene.head_frame_age_s() <= self._head_max_age
        grav = body.gravity_proj_z if body else -1.0
        pose_ok = grav <= -0.85
        policy = bool(body.rl_policy_active) if body else False
        motion = "moving" if self._fsm.state.value == "ACTING" else "idle"
        battery = None
        health = Health()
        if self._thermal is not None:
            snap = self._thermal.snapshot()
            battery = Battery(soc=snap.soc, temperature_c=snap.battery_temperature_c,
                              charging=snap.charging)
            health = Health(level="warning" if snap.faults else "ok", faults=snap.faults)
        core = CoreState(
            pose=None,
            safety_state=SafetyStateMsg(
                e_stop=False,
                geofence_ok=True,
                gravity_proj_z=grav,
                watchdog_ok=WatchdogOk(lowstate=lowstate_ok, head_frame=head_ok,
                                       pose=pose_ok),
            ),
            policy_active=policy,
            battery=battery,
            health=health,
        )
        ext = {}
        if body is not None:
            ext = {"g1_sim": {"mode_machine": body.mode_machine}}
        return RobotStateMsg(
            robot_id=self.robot_id, ts=_iso_now(), seq=seq,
            fsm_state=self._fsm.state.value, motion_state=motion,
            core=core, extensions=ext,
        )

    def get_safety_state(self) -> SafetyStateMsg:
        return self.get_state().core.safety_state

    async def subscribe_events(self) -> AsyncIterator[RobotEvent]:
        while True:
            yield await self._sink.queue.get()

    def snapshot_scene(self) -> SceneState:
        """Latest fused perception snapshot; the agent perception loop turns this
        into semantic RobotEvents (see fleet/agent/event_builder.py)."""
        return self._scene.snapshot()

    def admit(self, envelope) -> AdmissionDecision:
        """Delegate to the injected local AdmissionGate (final authority).

        If no gate was wired (pure read-only construction), there is no control
        path and admission is unsupported."""
        if self._admission_gate is None:
            raise NotImplementedError("admit() needs an admission_gate; none wired")
        return self._admission_gate.admit(envelope)
