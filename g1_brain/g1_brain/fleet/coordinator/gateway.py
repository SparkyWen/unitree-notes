"""CommandGateway — the single choke point for all down-bound commands.

Every CommandEnvelope is issued through here: it stamps idempotency, writes a
`command_issued` event, and pushes via the transport. Returned AdmissionDecisions
are recorded as `command_accepted`/`command_refused`, correlated back to the
originating trace_id. This is what makes every dispatch decision replayable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, Set

from g1_brain.fleet.contracts.models import (
    AdmissionDecision, CommandEnvelope, EventType, RobotEvent,
)

SendCommand = Callable[[str, CommandEnvelope], Awaitable[None]]


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class CommandGateway:
    def __init__(self, *, send_command: SendCommand, event_log):
        self._send = send_command
        self._log = event_log
        self._issued: Set[str] = set()
        self._trace_of: Dict[str, str] = {}  # command_id -> trace_id (for correlation)

    def issued_keys(self) -> Set[str]:
        return set(self._issued)

    async def issue(self, env: CommandEnvelope) -> bool:
        if env.idempotency_key in self._issued:
            return False
        self._issued.add(env.idempotency_key)
        self._trace_of[env.command_id] = env.trace_id
        self._log.append(RobotEvent.make(
            robot_id=env.issued_to, type=EventType.COMMAND_ISSUED, ts=_iso_now(),
            trace_id=env.trace_id,
            payload={"command_id": env.command_id, "capability": env.capability,
                     "payload": env.payload}))
        try:
            await self._send(env.issued_to, env)
        except KeyError:
            # robot not connected: undo idempotency so a later retry can succeed
            self._issued.discard(env.idempotency_key)
            self._log.append(RobotEvent.make(
                robot_id=env.issued_to, type=EventType.COMMAND_REFUSED, ts=_iso_now(),
                trace_id=env.trace_id,
                payload={"command_id": env.command_id, "reason_code": "NOT_CONNECTED"}))
            return False
        return True

    def record_admission(self, decision: AdmissionDecision) -> None:
        etype = (EventType.COMMAND_ACCEPTED if decision.decision == "accepted"
                 else EventType.COMMAND_REFUSED)
        self._log.append(RobotEvent.make(
            robot_id=decision.robot_id, type=etype, ts=_iso_now(),
            trace_id=self._trace_of.get(decision.command_id),
            payload={"command_id": decision.command_id,
                     "decision": decision.decision,
                     "reason_code": decision.reason_code,
                     "reason_detail": decision.reason_detail}))
