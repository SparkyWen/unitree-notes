"""In-process FleetBus (no WebSocket) for tests and the Tier-1 e2e scenario.

A ``LoopbackHub`` bundles the coordinator-side services (registry, event log,
perception aggregator, admission sink) and hands out per-robot ``LoopbackBus``
clients. It mirrors the WS transport's surface so the same RobotAgent /
CommandGateway code runs unchanged over either:

    coordinator  --send_command(robot_id, env)-->  robot.on_command(env)
                 <--admission_sink(decision)------  (returned decision)

The robot telemetry path (register/heartbeat/publish) writes directly into the
coordinator services, exactly like ws_server does on receipt of a frame.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional

from g1_brain.fleet.contracts.models import (
    AdmissionDecision, CapabilityDescriptor, CommandEnvelope, RobotEvent,
    RobotStateMsg,
)
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel


class LoopbackHub:
    """Coordinator-side hub for in-process wiring."""

    def __init__(self, *, registry: Optional[FleetRegistry] = None,
                 event_log: Optional[EventLog] = None,
                 perception_agg: Optional[PerceptionAggregator] = None,
                 admission_sink: Optional[Callable[[AdmissionDecision], None]] = None):
        self.registry = registry or FleetRegistry()
        if event_log is None:
            tmp = Path(tempfile.mkdtemp(prefix="fleet_loopback_")) / "events.sqlite"
            event_log = EventLog(tmp)
            event_log.init()
        self.event_log = event_log
        self.perception_agg = perception_agg or PerceptionAggregator(
            world_model=IdentityWorldModel())
        self.admission_sink = admission_sink
        self._conns: Dict[str, "LoopbackBus"] = {}

    def client(self) -> "LoopbackBus":
        return LoopbackBus(self)

    async def send_command(self, robot_id: str, env: CommandEnvelope) -> None:
        conn = self._conns.get(robot_id)
        if conn is None:
            raise KeyError(f"no connected robot {robot_id!r}")
        await conn._deliver(env)


class LoopbackBus:
    """Robot-side client bound to a LoopbackHub. Satisfies the RobotAgent's bus."""

    def __init__(self, hub: LoopbackHub):
        self._hub = hub
        self._robot_id: Optional[str] = None
        # Set by RobotAgent: async (CommandEnvelope) -> AdmissionDecision | None
        self.on_command: Optional[Callable[[CommandEnvelope], Awaitable[Optional[AdmissionDecision]]]] = None

    async def connect(self, cap: CapabilityDescriptor) -> None:
        self._robot_id = cap.robot_id
        self._hub.registry.register(cap)
        self._hub._conns[cap.robot_id] = self

    async def register(self, cap: CapabilityDescriptor) -> None:
        self._robot_id = cap.robot_id
        self._hub.registry.register(cap)

    async def heartbeat(self, st: RobotStateMsg) -> None:
        self._hub.registry.on_heartbeat(st)

    async def publish(self, ev: RobotEvent) -> None:
        self._hub.event_log.append(ev)
        self._hub.perception_agg.ingest(ev)

    async def _deliver(self, env: CommandEnvelope) -> None:
        if self.on_command is None:
            return
        decision = await self.on_command(env)
        if decision is not None and self._hub.admission_sink is not None:
            self._hub.admission_sink(decision)

    async def close(self) -> None:
        if self._robot_id is not None:
            self._hub._conns.pop(self._robot_id, None)
