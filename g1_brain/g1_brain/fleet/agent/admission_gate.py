"""AdmissionGate — the per-robot local final authority (doc §3.1.2, §18.2).

Every coordinator CommandEnvelope passes through here before the LocalPlanner
applies it. The gate can refuse — refusal is a first-class outcome. Checks, in
order: TTL expiry -> idempotency -> capability supported -> FSM legality ->
apply. This is the safety boundary the coordinator can never bypass.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Set

from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.contracts.models import AdmissionDecision, CommandEnvelope
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Which FSM states each capability may be admitted from.
_TASK_CAPS = {"patrol", "resume_task", "idle", "stop"}


class AdmissionGate:
    def __init__(self, *, robot_id: str, fsm: RobotFsm, planner: LocalPlanner,
                 supported_capabilities: Set[str],
                 clock: Callable[[], float] = time.time):
        self._robot_id = robot_id
        self._fsm = fsm
        self._planner = planner
        self._supported = set(supported_capabilities)
        self._clock = clock
        self._seen: Set[str] = set()

    def _refuse(self, env: CommandEnvelope, code: str, detail: str = "") -> AdmissionDecision:
        return AdmissionDecision(command_id=env.command_id, robot_id=self._robot_id,
                                 decision="refused", reason_code=code,
                                 reason_detail=detail, ts=_iso_now())

    def _fsm_allows(self, capability: str) -> bool:
        state = self._fsm.state
        if state in (RobotFsmState.EMERGENCY_STOP, RobotFsmState.FAULT):
            return False  # safety states accept nothing from the center
        if capability in _TASK_CAPS:
            return state == RobotFsmState.STANDING  # must be awake & available
        # sleep / wake are allowed from any non-safety state
        return True

    def admit(self, env: CommandEnvelope) -> AdmissionDecision:
        if self._clock() > env.expires_at:
            return self._refuse(env, "EXPIRED", "command past expires_at")
        if env.idempotency_key in self._seen:
            return self._refuse(env, "DUPLICATE", "idempotency key already processed")
        if env.capability not in self._supported:
            return self._refuse(env, "UNSUPPORTED_CAPABILITY", env.capability)
        if not self._fsm_allows(env.capability):
            return self._refuse(env, "FSM_FORBIDDEN",
                                f"{env.capability} not allowed in {self._fsm.state.value}")
        try:
            self._planner.apply(env)
        except Exception as e:  # noqa: BLE001
            return self._refuse(env, "PLAN_ERROR", str(e))
        self._seen.add(env.idempotency_key)
        return AdmissionDecision(command_id=env.command_id, robot_id=self._robot_id,
                                 decision="accepted", reason_code="OK", ts=_iso_now())
