"""LocalPlanner — the robot's slow-brain seam (doc §18.3).

Maps an *admitted* capability contract into a local posture + FSM transition +
lifecycle event. It is deterministic and never lets the coordinator touch
motors directly: it only chooses a Posture for the MotionBackend. An optional
``explain_hook`` may call an LLM, but it is never on the control path.
"""
from __future__ import annotations

from typing import Callable, Optional

from g1_brain.fleet.agent.motion.base import MotionBackend, Posture
from g1_brain.fleet.clock import iso_now as _iso_now
from g1_brain.fleet.contracts.models import CommandEnvelope, EventType, RobotEvent
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState

EmitFn = Callable[[RobotEvent], None]


class LocalPlanner:
    def __init__(self, *, robot_id: str, fsm: RobotFsm, backend: MotionBackend,
                 emit: EmitFn, explain_hook: Optional[Callable[[CommandEnvelope], str]] = None):
        self._robot_id = robot_id
        self._fsm = fsm
        self._backend = backend
        self._emit = emit
        self.explain_hook = explain_hook  # optional; never on the control path

    def _event(self, etype: EventType, env: CommandEnvelope, payload: dict) -> None:
        self._emit(RobotEvent.make(robot_id=self._robot_id, type=etype,
                                   ts=_iso_now(), payload=payload,
                                   trace_id=env.trace_id))

    def apply(self, env: CommandEnvelope) -> None:
        cap = env.capability
        if cap == "sleep":
            if self._fsm.state == RobotFsmState.DORMANT:
                return  # already asleep: idempotent no-op, no spurious event
            # ensure we reach STANDING first (ACTING/ENGAGED -> STANDING -> DORMANT)
            if self._fsm.state in (RobotFsmState.ACTING, RobotFsmState.ENGAGED):
                self._fsm.transition(RobotFsmState.STANDING, "pre-sleep")
            self._fsm.transition(RobotFsmState.DORMANT, "sleep")
            self._backend.set_posture(Posture.SLEEP)
            self._event(EventType.ROBOT_SLEEPING, env,
                        {"reason": env.payload.get("reason", "")})
        elif cap == "wake":
            if self._fsm.state == RobotFsmState.STANDING:
                return  # already awake: idempotent no-op
            if self._fsm.state == RobotFsmState.DORMANT:
                self._fsm.transition(RobotFsmState.STANDING, "wake")
            self._backend.set_posture(Posture.ACTIVE)
            self._event(EventType.ROBOT_RESUMED, env, {})
        elif cap in ("patrol", "resume_task"):
            self._backend.set_posture(Posture.PATROL)
            self._event(EventType.TASK_ASSIGNED, env,
                        {"task_id": env.payload.get("task_id"), "type": "patrol"})
        elif cap == "idle":
            self._backend.set_posture(Posture.IDLE)
        elif cap == "stop":
            self._backend.set_posture(Posture.STOP)
