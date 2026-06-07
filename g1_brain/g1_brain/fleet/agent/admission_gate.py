"""AdmissionGate — the per-robot local final authority (doc §3.1.2, §18.2).

Every coordinator CommandEnvelope passes through here before the LocalPlanner
applies it. The gate can refuse — refusal is a first-class outcome. Checks, in
order: TTL expiry -> idempotency -> capability supported -> FSM legality ->
apply. This is the safety boundary the coordinator can never bypass.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, Set

from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.clock import iso_now as _iso_now
from g1_brain.fleet.contracts.models import AdmissionDecision, CommandEnvelope
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState

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
        # idempotency keys -> expiry epoch; pruned each admit so it stays bounded
        # by the set of in-flight commands (no unbounded growth, and a key is
        # reusable once its command window has lapsed).
        self._seen: Dict[str, float] = {}

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
        # sleep: STANDING (apply) or DORMANT (idempotent no-op); wake: the reverse.
        if capability == "sleep":
            return state in (RobotFsmState.STANDING, RobotFsmState.DORMANT)
        if capability == "wake":
            return state in (RobotFsmState.DORMANT, RobotFsmState.STANDING)
        return False

    def admit(self, env: CommandEnvelope) -> AdmissionDecision:
        now = self._clock()
        # prune expired idempotency keys -> set stays bounded by in-flight commands
        if self._seen:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
        if now > env.expires_at:
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
        self._seen[env.idempotency_key] = env.expires_at
        return AdmissionDecision(command_id=env.command_id, robot_id=self._robot_id,
                                 decision="accepted", reason_code="OK", ts=_iso_now())
